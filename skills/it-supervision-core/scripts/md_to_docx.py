#!/usr/bin/env python3
"""把监理文书 Markdown 渲染为可打印、可签章的 DOCX。

支持的 Markdown 子集：# 标题、##/###/#### 小标题、段落、**加粗**、`代码`、[链接](url)（转纯文本）、
- 列表 / 1. 列表 / - [ ] 复选框、> 引用、管道表格（单元格内 <br> 换行）、
<!-- pagebreak --> 分页、<!-- signature:xxx --> 签章栏（不跨页、与上文同页）。

用法：
  python3 md_to_docx.py 文书.md [-o 输出目录或文件.docx] [--header "页眉文字"] [--profile 监理资料/项目档案.yaml]
依赖：python-docx（pip install python-docx）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 python-docx，请先执行：pip install python-docx")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_profile_scalar  # noqa: E402

FONT_SETS = {
    "win": {"body": "仿宋", "title": "宋体", "head": "黑体", "quote": "楷体"},
    "mac": {"body": "Songti SC", "title": "Songti SC", "head": "Heiti SC", "quote": "Songti SC"},
}
FONT_BODY, FONT_TITLE, FONT_HEAD, FONT_QUOTE = (FONT_SETS["win"][k] for k in ("body", "title", "head", "quote"))
FORM_FIRST_CELLS = {"文书编号", "项目", "项目名称"}

INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|<br\s*/?>)")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
COMMENT = re.compile(r"^\s*<!--\s*(.*?)\s*-->\s*$")


def set_font(run, name: str, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)
    if size:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def add_inline(paragraph, text: str, font: str, size: float, bold: bool = False) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if re.fullmatch(r"<br\s*/?>", part):
            paragraph.add_run().add_break()
            continue
        run_bold = bold
        if part.startswith("**") and part.endswith("**"):
            part, run_bold = part[2:-2], True
        elif part.startswith("`") and part.endswith("`"):
            part = part[1:-1]
        elif part.startswith("["):
            part = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", part)
        set_font(paragraph.add_run(part), font, size, run_bold)


def fmt(paragraph, *, align=None, first_indent: bool = False, space_after: float = 0, keep_next: bool = False,
        line_spacing: float = 1.5) -> None:
    pf = paragraph.paragraph_format
    if align is not None:
        paragraph.alignment = align
    pf.line_spacing = line_spacing
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(0)
    if first_indent:
        pf.first_line_indent = Pt(24)
    if keep_next:
        pf.keep_with_next = True


def add_field(paragraph, instr: str, font: str, size: float) -> None:
    run = paragraph.add_run()
    set_font(run, font, size)
    for tag, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if tag:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        elif text == instr:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = f" {instr} "
        else:
            el = OxmlElement("w:t")
            el.text = text
        run._element.append(el)


def setup_document(header_text: str | None, landscape: bool):
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = FONT_BODY
    normal.font.size = Pt(12)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT_BODY)

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = sec.page_height, sec.page_width
    sec.top_margin = sec.bottom_margin = Cm(2.54)
    sec.left_margin, sec.right_margin = Cm(2.8), Cm(2.6)

    if header_text:
        hp = sec.header.paragraphs[0]
        add_inline(hp, header_text, FONT_BODY, 9)
        fmt(hp, align=WD_ALIGN_PARAGRAPH.CENTER, line_spacing=1.0)
        p_pr = hp._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "000000")):
            bottom.set(qn(k), v)
        bdr.append(bottom)
        p_pr.append(bdr)

    fp = sec.footer.paragraphs[0]
    fmt(fp, align=WD_ALIGN_PARAGRAPH.CENTER, line_spacing=1.0)
    set_font(fp.add_run("第 "), FONT_BODY, 9)
    add_field(fp, "PAGE", FONT_BODY, 9)
    set_font(fp.add_run(" 页  共 "), FONT_BODY, 9)
    add_field(fp, "NUMPAGES", FONT_BODY, 9)
    set_font(fp.add_run(" 页"), FONT_BODY, 9)
    return doc


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [c.strip().replace("\\|", "|") for c in cells]


def display_len(text: str) -> int:
    longest = max((len(seg) for seg in re.split(r"<br\s*/?>", text)), default=0)
    return max(2, longest)


def add_table(doc, rows: list[list[str]], signature: bool, usable_cm: float) -> None:
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 表头信息表（首格为“文书编号”等）：不设表头行，标签列加粗
    form = rows[0][0].strip("* ") in FORM_FIRST_CELLS and ncols in (2, 4, 6)
    weights = [min(30, max(display_len(r[i]) for r in rows)) for i in range(ncols)]
    total = sum(weights)
    widths = [Cm(max(1.2, usable_cm * w / total)) for w in weights]

    for ri, row in enumerate(rows):
        tr = table.rows[ri]
        tr_pr = tr._tr.get_or_add_trPr()
        if signature or ri == 0 or form:
            tr_pr.append(OxmlElement("w:cantSplit"))
        if ri == 0 and not form:
            tr_pr.append(OxmlElement("w:tblHeader"))
        for ci, text in enumerate(row):
            cell = tr.cells[ci]
            cell.width = widths[ci]
            p = cell.paragraphs[0]
            bold = (ci % 2 == 0) if form else ri == 0
            align = WD_ALIGN_PARAGRAPH.CENTER if (ri == 0 and not form) else None
            add_inline(p, text, FONT_BODY, 10.5, bold)
            fmt(p, align=align, line_spacing=1.25, keep_next=signature)


def convert(md_path: Path, out_path: Path, header: str | None, landscape: bool) -> Path:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = setup_document(header, landscape)
    sec = doc.sections[0]
    usable_cm = (sec.page_width - sec.left_margin - sec.right_margin) / 360000

    i, title_done, pending_signature, in_code = 0, False, False, False
    last_para = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            p = doc.add_paragraph()
            add_inline(p, line, "Consolas", 9)
            fmt(p, line_spacing=1.0)
            i += 1
            continue

        cm = COMMENT.match(stripped)
        if cm:
            directive = cm.group(1)
            if directive == "pagebreak":
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif directive.startswith("signature"):
                pending_signature = True
                if last_para is not None:
                    last_para.paragraph_format.keep_with_next = True
            i += 1
            continue
        if stripped.startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue

        if not stripped or re.fullmatch(r"-{3,}|\*{3,}", stripped):
            i += 1
            continue

        if stripped.startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            rows = [split_row(stripped)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            add_table(doc, rows, pending_signature, usable_cm)
            pending_signature = False
            spacer = doc.add_paragraph()
            fmt(spacer, line_spacing=1.0)
            last_para = spacer
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if h:
            level, text = len(h.group(1)), h.group(2).strip()
            p = doc.add_paragraph()
            if level == 1 and not title_done:
                add_inline(p, text, FONT_TITLE, 22, True)
                fmt(p, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12, keep_next=True)
                title_done = True
            else:
                size = {1: 16, 2: 15, 3: 14}.get(level, 12)
                add_inline(p, text, FONT_HEAD, size, level <= 4)
                fmt(p, space_after=6, keep_next=True)
                p.paragraph_format.space_before = Pt(10 if level <= 2 else 6)
            last_para = p
            i += 1
            continue

        if stripped.startswith(">"):
            p = doc.add_paragraph()
            add_inline(p, stripped.lstrip("> ").strip(), FONT_QUOTE, 11)
            fmt(p)
            p.paragraph_format.left_indent = Cm(0.74)
            last_para = p
            i += 1
            continue

        lm = re.match(r"^(\s*)([-*+]|\d+[.、)])\s+(\[[ xX]\]\s+)?(.*)$", line)
        if lm:
            indent, marker, box, text = lm.groups()
            if box:
                prefix = "☑ " if box.strip("[] ").lower() == "x" else "☐ "
            elif marker in "-*+":
                prefix = "· "
            else:
                prefix = marker + " "
            p = doc.add_paragraph()
            add_inline(p, prefix + text, FONT_BODY, 12)
            fmt(p)
            p.paragraph_format.left_indent = Cm(0.74 * (1 + len(indent.replace("\t", "  ")) // 2))
            p.paragraph_format.first_line_indent = Cm(-0.5)
            last_para = p
            i += 1
            continue

        buf = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||>|```|<!--|\s*([-*+]|\d+[.、)])\s)", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        p = doc.add_paragraph()
        add_inline(p, "".join(buf), FONT_BODY, 12)
        fmt(p, first_indent=True)
        last_para = p

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="监理文书 Markdown → DOCX")
    ap.add_argument("markdown", nargs="+")
    ap.add_argument("-o", "--output", help="输出目录或 .docx 文件（默认与源文件同目录）")
    ap.add_argument("--header", help="页眉文字（默认：项目名称 + 监理单位，取自项目档案）")
    ap.add_argument("--profile", default="监理资料/项目档案.yaml")
    ap.add_argument("--landscape", action="store_true", help="横向页面（宽表格清单适用）")
    ap.add_argument("--fonts", choices=sorted(FONT_SETS), default="win",
                    help="字体方案：win=仿宋/宋体/黑体（Windows/WPS，默认）；mac=macOS 自带中文字体")
    args = ap.parse_args()

    global FONT_BODY, FONT_TITLE, FONT_HEAD, FONT_QUOTE
    fs = FONT_SETS[args.fonts]
    FONT_BODY, FONT_TITLE, FONT_HEAD, FONT_QUOTE = fs["body"], fs["title"], fs["head"], fs["quote"]

    header = args.header
    if header is None:
        profile = Path(args.profile)
        name = read_profile_scalar(profile, "项目名称")
        if name and "【待填】" not in name:
            header = name
            text = profile.read_text(encoding="utf-8") if profile.exists() else ""
            m = re.search(r"^监理单位:\s*\n\s+名称:\s*(\S+)", text, re.M)
            if m and "【待填】" not in m.group(1):
                header += "　　" + m.group(1)

    for src in map(Path, args.markdown):
        if args.output:
            out = Path(args.output)
            if out.suffix.lower() != ".docx":
                out = out / (src.stem + ".docx")
        else:
            out = src.with_suffix(".docx")
        landscape = args.landscape or "<!-- landscape -->" in src.read_text(encoding="utf-8")
        print(f"已生成：{convert(src, out, header, landscape)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
