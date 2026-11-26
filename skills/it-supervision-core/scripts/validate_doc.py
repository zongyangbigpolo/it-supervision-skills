#!/usr/bin/env python3
"""校验监理文书 Markdown 草稿。

检查项：
  1. 是否含文书编号（JL-XXX-TZ-2026-001 形式）；
  2. 是否含签章栏标记 <!-- signature:... -->；
  3. 是否残留【待填】（--final 时为错误，否则为警告）；
  4. 按类型码检查必备章节关键词；
  5. 通知单类：每个问题是否写明“依据”和“期限”。

用法：python3 validate_doc.py <file.md> [--final]
退出码：0 通过；1 有错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PLACEHOLDER  # noqa: E402

DOC_NO = re.compile(r"\b[A-Z]{1,6}-[A-Z0-9]{2,10}-([A-Z]{2})-\d{4}-\d{3}\b")
SIGNATURE = re.compile(r"<!--\s*signature:[\w-]+\s*-->")

REQUIRED = {
    "GH": ["工程概况", "监理范围", "监理依据", "监理组织", "质量控制", "进度控制", "投资控制", "合同管理", "信息管理", "组织协调"],
    "RZ": ["天气", "工作内容", "问题", "处理"],
    "TZ": ["事由", "依据", "要求", "期限"],
    "ZT": ["暂停", "原因", "范围"],
    "FG": ["复工"],
    "YS": ["验收范围", "验收依据", "检查情况", "遗留问题", "验收结论"],
    "DB": ["定级", "备案", "测评", "整改", "结论"],
    "DH": ["合同", "序列号", "数量", "外观", "结论"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--final", action="store_true", help="正式件模式：残留【待填】视为错误")
    args = ap.parse_args()

    text = Path(args.file).read_text(encoding="utf-8")
    errors: list[str] = []
    warns: list[str] = []

    m = DOC_NO.search(text)
    code = m.group(1) if m else None
    if not m:
        errors.append("未找到文书编号（如 JL-ZHZW-TZ-2026-001），请用 next_doc_no.py 分配。")

    if not SIGNATURE.search(text):
        errors.append("缺少签章栏标记 <!-- signature:... -->，见 references/签章栏规范.md。")

    holes = [i + 1 for i, line in enumerate(text.splitlines()) if PLACEHOLDER in line]
    if holes:
        msg = f"残留 {len(holes)} 处 {PLACEHOLDER}（行号：{', '.join(map(str, holes[:20]))}{' …' if len(holes) > 20 else ''}）"
        (errors if args.final else warns).append(msg)

    if code in REQUIRED:
        missing = [k for k in REQUIRED[code] if k not in text]
        if missing:
            errors.append(f"类型 {code} 缺少必备内容关键词：{'、'.join(missing)}")

    if code == "TZ":
        for b in re.split(r"\n(?=#{2,4}\s*问题\s*\d+)", text)[1:]:
            b = re.split(r"\n#{1,3}\s(?!问题)", b)[0]
            head = b.strip().splitlines()[0].lstrip("# ")[:40]
            for key in ("依据", "期限"):
                if not re.search(rf"{key}\**\s*[：:]", b):
                    errors.append(f"「{head}」未写明{key}")

    for w in warns:
        print(f"[警告] {w}")
    for e in errors:
        print(f"[错误] {e}")
    if not errors:
        print("[通过] 校验通过" + ("（正式件）" if args.final else "（草稿）"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
