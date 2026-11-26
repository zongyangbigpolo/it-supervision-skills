import csv
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "skills" / "it-supervision-core" / "scripts"
EXAMPLE = ROOT / "examples" / "示例-智慧政务平台"
sys.path.insert(0, str(CORE))

from common import amount_to_chinese  # noqa: E402

TEMPLATE_TYPES = {
    "监理规划.md": "GH", "监理实施细则.md": "XZ", "监理日志.md": "RZ", "监理周报.md": "ZB",
    "监理通知单.md": "TZ", "监理通知回复单.md": "HF", "工程暂停令.md": "ZT", "复工令.md": "FG",
    "监理工作联系单.md": "LX", "阶段验收监理意见.md": "YS", "等保测评监理检查表.md": "DB",
    "等保整改跟踪表.md": "ZG", "硬件设备到货验收单.md": "DH",
}


def run(*args, cwd=None):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True)


class AmountTest(unittest.TestCase):
    def test_amounts(self):
        cases = {
            "123400": "壹拾贰万叁仟肆佰元整",
            "100000001": "壹亿零壹元整",
            "10010": "壹万零壹拾元整",
            "1005.07": "壹仟零伍元零柒分",
            "20000000": "贰仟万元整",
            "0.5": "伍角整",
            "0": "零元整",
        }
        for value, expected in cases.items():
            self.assertEqual(amount_to_chinese(value), expected, value)


class NumberingTest(unittest.TestCase):
    def test_increments_per_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "监理资料"
            root.mkdir()
            (root / "项目档案.yaml").write_text("项目简称: ABC\n编号前缀: JL\n", encoding="utf-8")
            outs = [run(CORE / "next_doc_no.py", "--type", t, "--root", root, "--year", "2026").stdout.strip()
                    for t in ("TZ", "TZ", "RZ")]
            self.assertEqual(outs, ["JL-ABC-TZ-2026-001", "JL-ABC-TZ-2026-002", "JL-ABC-RZ-2026-001"])
            with (root / "编号台账.csv").open(encoding="utf-8-sig") as f:
                self.assertEqual(len(list(csv.DictReader(f))), 3)

    def test_missing_abbr_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run(CORE / "next_doc_no.py", "--type", "TZ", "--root", tmp)
            self.assertEqual(r.returncode, 2)


class TemplateTest(unittest.TestCase):
    def test_all_templates_validate_and_render(self):
        templates = sorted((ROOT / "skills").glob("*/templates/*.md"))
        self.assertEqual({t.name for t in templates}, set(TEMPLATE_TYPES))
        with tempfile.TemporaryDirectory() as tmp:
            for t in templates:
                code = TEMPLATE_TYPES[t.name]
                text = t.read_text(encoding="utf-8")
                filled = re.sub(r"(\| 文书编号 \| )【待填】", rf"\1JL-TEST-{code}-2026-001", text, count=1)
                draft = Path(tmp) / t.name
                draft.write_text(filled, encoding="utf-8")
                r = run(CORE / "validate_doc.py", draft)
                self.assertEqual(r.returncode, 0, f"{t.name}\n{r.stdout}")
                r = run(CORE / "validate_doc.py", draft, "--final")
                self.assertEqual(r.returncode, 1, f"{t.name} 含【待填】时正式件校验应失败")
                r = run(CORE / "md_to_docx.py", draft, "-o", tmp, "--header", "测试")
                self.assertEqual(r.returncode, 0, f"{t.name}\n{r.stderr}")
                self.assertTrue((Path(tmp) / (t.stem + ".docx")).exists())

    def test_notice_requires_basis_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "tz.md"
            doc.write_text("# 监理通知单\n| 文书编号 | JL-AB-TZ-2026-001 |\n|---|---|\n\n事由：x 要求 依据 期限\n\n"
                           "### 问题 1：缺依据\n- 事实：x\n- 期限：2026年1月1日\n\n<!-- signature:issue-receive -->\n",
                           encoding="utf-8")
            r = run(CORE / "validate_doc.py", doc)
            self.assertEqual(r.returncode, 1)
            self.assertIn("未写明依据", r.stdout)


class ExampleTest(unittest.TestCase):
    def test_example_notice_passes_final(self):
        notice = next((EXAMPLE / "监理资料" / "03-监理通知单").glob("*.md"))
        r = run(CORE / "validate_doc.py", notice, "--final")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_compare_delivery_finds_issues(self):
        r = run(ROOT / "skills" / "hardware-arrival-check" / "scripts" / "compare_delivery.py",
                EXAMPLE / "输入资料" / "合同设备清单.csv", EXAMPLE / "输入资料" / "第1批到货清单.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("SW-9300", r.stdout)
        self.assertRegex(r.stdout, r"SN-A0003 \| 3、4")
        self.assertIn("伍拾万贰仟元整", r.stdout)

    def test_compare_delivery_cumulative(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch2 = Path(tmp) / "b2.csv"
            batch2.write_text("序号,合同项号,设备名称,品牌,型号,序列号,外观,加电,备注\n"
                              "1,1,机架式服务器,示例品牌A,SRV-2288,SN-A0001,合格,正常,\n", encoding="utf-8")
            r = run(ROOT / "skills" / "hardware-arrival-check" / "scripts" / "compare_delivery.py",
                    EXAMPLE / "输入资料" / "合同设备清单.csv", batch2,
                    "--previous", EXAMPLE / "输入资料" / "第1批到货清单.csv")
            self.assertIn("| 1 | 机架式服务器 | 示例品牌A SRV-2288 | 6 | 1 | 5 | 尚缺 1 |", r.stdout)
            self.assertRegex(r.stdout, r"SN-A0001 \| 1")


class PhotoTest(unittest.TestCase):
    MATCH = ROOT / "skills" / "site-photos" / "scripts" / "photo_match.py"

    def setUp(self):
        from PIL import Image

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        photos = self.dir / "照片" / "SN-B0002"
        photos.mkdir(parents=True)
        for name, folder in [("SN-A0001_铭牌.jpg", None), ("服务器_20261120.jpg", None), ("服务器_20261120(1).jpg", None),
                             ("机房全景_20261121.jpg", None), ("加电.jpg", photos)]:
            Image.new("RGB", (40, 30), (120, 120, 120)).save((folder or photos.parent) / name)
        (self.dir / "识别.csv").write_text("照片文件,文字\n服务器_20261120.jpg,2026-11-20 10:01 SN:SN-AOOO3 加电\n",
                                         encoding="utf-8")
        self.doc = self.dir / "单.md"
        self.doc.write_text(
            "# 到货验收单\n\n| 序号 | 序列号 | 现场照片 |\n|---|---|---|\n"
            "| 1 | SN-A0001 | {{照片:SN-A0001}} |\n| 2 | SN-B0002 | {{照片:SN-B0002}} |\n"
            "| 3 | SN-A0003 | {{照片:SN-A0003}} |\n| 4 | SN-C0004 | {{照片:SN-C0004}} |\n\n"
            "- **现场照片：** {{照片:日期=2026-11-21&机房}}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_match_and_render(self):
        out = self.dir / "匹配"
        r = run(self.MATCH, self.dir / "照片", "--doc", self.doc, "-o", out, "--ocr", "none",
                "--extra-text", self.dir / "识别.csv")
        self.assertEqual(r.returncode, 1, r.stderr)
        with (out / "照片匹配表.csv").open(encoding="utf-8-sig") as f:
            rows = {(x["占位符"], x["照片文件"]): x for x in csv.DictReader(f)}
        self.assertEqual(rows[("SN-A0001", "SN-A0001_铭牌.jpg")]["置信度"], "高")
        self.assertIn(("SN-B0002", "SN-B0002/加电.jpg"), rows)
        self.assertEqual(rows[("SN-A0003", "服务器_20261120.jpg")]["置信度"], "中")  # OCR 把 0 认成 O
        self.assertIn(("日期=2026-11-21&机房", "机房全景_20261121.jpg"), rows)
        self.assertFalse(any(k[0] == "SN-C0004" for k in rows))
        report = (out / "照片匹配报告.md").read_text(encoding="utf-8")
        self.assertIn("SN-C0004", report)
        self.assertIn("服务器_20261120(1).jpg", report)

        r = run(CORE / "md_to_docx.py", self.doc, "--photos", out / "照片匹配表.csv", "-o", self.dir, "--header", "测试")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SN-C0004", r.stdout)
        from docx import Document

        d = Document(self.dir / "单.docx")
        self.assertEqual(len(d.inline_shapes), 4)
        cell_pics = [len(row.cells[2]._tc.xpath(".//pic:pic")) for row in d.tables[0].rows[1:]]
        self.assertEqual(cell_pics, [1, 1, 1, 0])
        self.assertIn("【待补照片：SN-C0004】", d.tables[0].rows[4].cells[2].text)


class SkillMetadataTest(unittest.TestCase):
    def test_frontmatter_and_links(self):
        for skill in sorted((ROOT / "skills").iterdir()):
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            m = re.match(r"^---\nname: ([a-z0-9-]+)\ndescription: >\n(.*?)\nlicense:", text, re.S)
            self.assertIsNotNone(m, skill.name)
            self.assertEqual(m.group(1), skill.name)
            self.assertLess(len(m.group(2)), 1024, f"{skill.name} description 过长")
            for link in re.findall(r"\]\(([^)#]+)\)", text):
                if not link.startswith("http"):
                    self.assertTrue((skill / link).exists(), f"{skill.name}: 链接不存在 {link}")


if __name__ == "__main__":
    unittest.main()
