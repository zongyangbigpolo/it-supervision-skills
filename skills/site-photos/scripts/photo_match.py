#!/usr/bin/env python3
"""现场照片自动匹配：遍历照片文件夹，按“文件名 + 文件夹名 + 水印文字(OCR) + 拍摄时间”
匹配到监理文书中的 {{照片:关键字}} 占位符，输出可人工修改的《照片匹配表.csv》与《照片匹配报告.md》。

用法：
  python3 photo_match.py <照片文件夹> --doc 文书.md [--doc 另一份.md] [-o 监理资料/照片匹配]
        [--ocr auto|rapidocr|paddleocr|tesseract|none] [--extra-text 人工识别.csv] [--max-per-slot 4]

确认匹配表后渲染：
  python3 md_to_docx.py 文书.md --photos 监理资料/照片匹配/照片匹配表.csv -o 监理资料/正式件/

OCR 依赖（任选其一，推荐第一个）：
  pip install rapidocr onnxruntime        # 轻量，中文识别好，无需 GPU
  pip install paddleocr paddlepaddle
  pip install pytesseract  （另需安装 tesseract 与 chi_sim 语言包）
退出码：0 全部照片位都有照片且无待确认；1 存在缺照片 / 待确认 / 未匹配照片；2 输入错误。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[2] / "it-supervision-core" / "scripts"
sys.path.insert(0, str(CORE))
from photos import IMAGE_EXTS, MAP_FIELDS, Image, ImageOps, find_placeholders  # noqa: E402

LEVELS = {"高": 3, "中": 2, "低": 1, "": 0}
CONFUSE = str.maketrans("OQDILZSB", "00011258")
DATE_SEP = re.compile(r"(20\d{2})\s*[-/.年_]\s*(\d{1,2})\s*[-/.月_]\s*(\d{1,2})")
DATE_COMPACT = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/.#]*")
CJK = re.compile(r"[\u4e00-\u9fff]")
DATE_TERM = re.compile(r"(?:日期|date)\s*[=＝:：]\s*(.+)", re.I)


# ---------- 文本与日期 ----------

def norm(s: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", s.upper())


def compact(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def find_dates(text: str) -> list[str]:
    out = []
    for rx in (DATE_SEP, DATE_COMPACT):
        for y, m, d in rx.findall(text):
            try:
                out.append(dt.date(int(y), int(m), int(d)).isoformat())
            except ValueError:
                pass
    return list(dict.fromkeys(out))


def exif_datetime(path: Path) -> str:
    if Image is None:
        return ""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
        if raw:
            return dt.datetime.strptime(str(raw).strip()[:19], "%Y:%m:%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        pass
    return ""


# ---------- OCR ----------

def quiet_logs() -> None:
    for name in ("RapidOCR", "rapidocr", "ppocr", "paddleocr", "paddlex"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        for h in lg.handlers:
            h.setLevel(logging.ERROR)


def make_ocr(engine: str):
    tried = []
    if engine in ("auto", "rapidocr"):
        try:
            from rapidocr import RapidOCR

            eng = RapidOCR()
            quiet_logs()
            return "rapidocr", lambda p: list(eng(p).txts or [])
        except Exception as exc:  # noqa: BLE001
            tried.append(f"rapidocr: {exc.__class__.__name__}")
        try:
            from rapidocr_onnxruntime import RapidOCR

            eng = RapidOCR()
            quiet_logs()
            return "rapidocr", lambda p: [r[1] for r in (eng(p)[0] or [])]
        except Exception as exc:  # noqa: BLE001
            tried.append(f"rapidocr_onnxruntime: {exc.__class__.__name__}")
    if engine in ("auto", "paddleocr"):
        try:
            from paddleocr import PaddleOCR

            eng = PaddleOCR(lang="ch")
            quiet_logs()

            def run(p):
                res = eng.predict(p) if hasattr(eng, "predict") else eng.ocr(p)
                texts = []
                for page in res or []:
                    if hasattr(page, "get"):
                        texts += list(page.get("rec_texts", []))
                    else:
                        texts += [ln[1][0] for ln in page or []]
                return texts

            return "paddleocr", run
        except Exception as exc:  # noqa: BLE001
            tried.append(f"paddleocr: {exc.__class__.__name__}")
    if engine in ("auto", "tesseract"):
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return "tesseract", lambda p: pytesseract.image_to_string(p, lang="chi_sim+eng").splitlines()
        except Exception as exc:  # noqa: BLE001
            tried.append(f"tesseract: {exc.__class__.__name__}")
    if engine != "none":
        print("[提示] 未找到可用的 OCR 引擎，只按文件名/文件夹名/EXIF 匹配。安装：pip install rapidocr onnxruntime"
              f"（尝试结果：{'; '.join(tried)}）", file=sys.stderr)
    return "", None


def has_code(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]{5,}", re.sub(r"[-_/.: ]", "", text)))


def ocr_image(path: Path, runner, max_px: int = 2400) -> str:
    """识别水印文字；若未识别出编码类文字，再尝试旋转 180°/90°/270°（应对倒置或侧拍照片）。"""
    if Image is None:
        return "\n".join(runner(str(path)))
    with Image.open(path) as im:
        base = ImageOps.exif_transpose(im).convert("RGB")
    base.thumbnail((max_px, max_px))
    fd, tmp = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    best = ""
    try:
        for angle in (0, 180, 90, 270):
            (base.rotate(angle, expand=True) if angle else base).save(tmp, quality=90)
            text = "\n".join(t for t in runner(tmp) if t)
            if has_code(text):
                return text
            if len(text) > len(best):
                best = text
        return best
    finally:
        os.unlink(tmp)


def file_sig(path: Path) -> str:
    st = path.stat()
    return hashlib.md5(f"{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()


# ---------- 匹配 ----------

def match_term(term: str, texts: dict[str, str]) -> tuple[str, str]:
    """单个关键字在各来源文本中的最佳匹配 → (置信度, 来源)。"""
    best = ("", "")
    if CJK.search(term):
        t = compact(term)
        for src, text in texts.items():
            if t and t in compact(text):
                return "高", src
        return best
    key = norm(term)
    if not key:
        return best
    kc = key.translate(CONFUSE)
    for src, text in texts.items():
        toks = {norm(t) for t in TOKEN_RE.findall(text)} - {""}
        level = ""
        if key in toks:
            level = "高"
        elif len(key) >= 5 and any(len(t) <= len(key) + 4 and (t.endswith(key) or t.startswith(key)) for t in toks):
            level = "中"
        elif len(key) >= 5 and kc in {t.translate(CONFUSE) for t in toks}:
            level = "中"
        elif len(key) >= 8 and any(len(t) >= len(key) - 1 and
                                   difflib.SequenceMatcher(None, kc, t.translate(CONFUSE)).ratio() >= 0.9 for t in toks):
            level = "低"
        if LEVELS[level] > LEVELS[best[0]]:
            best = (level, src)
    return best


def match_slot(slot: str, photo: dict) -> tuple[str, str]:
    """占位符：'|' 分隔“或”，'&' 分隔“且”，'日期=YYYY-MM-DD' 为日期条件。"""
    best = ("", "")
    for alt in slot.split("|"):
        levels, sources = [], []
        for term in [t.strip() for t in alt.split("&") if t.strip()]:
            m = DATE_TERM.fullmatch(term)
            if m:
                want = find_dates(m.group(1))
                hit = [s for s, ds in photo["dates"].items() if want and want[0] in ds]
                levels.append("高" if hit else "")
                sources.append("日期(" + "/".join(hit) + ")" if hit else "")
            else:
                lv, src = match_term(term, photo["texts"])
                levels.append(lv)
                sources.append(f"{src}:{term}" if lv else "")
            if not levels[-1]:
                break
        if levels and all(levels):
            level = min(levels, key=LEVELS.get)
            if LEVELS[level] > LEVELS[best[0]]:
                best = (level, "；".join(sources))
    return best


def slot_label(slot: str) -> str:
    alt = slot.split("|")[0]
    return "　".join(t.strip() for t in alt.split("&") if t.strip() and not DATE_TERM.fullmatch(t.strip())) or ""


def is_date_only(slot: str) -> bool:
    return all(DATE_TERM.fullmatch(t.strip()) for t in slot.split("|")[0].split("&") if t.strip())


# ---------- 主流程 ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="现场照片自动匹配到监理文书照片位")
    ap.add_argument("folder", help="照片文件夹（递归遍历子文件夹）")
    ap.add_argument("--doc", action="append", required=True, help="含 {{照片:…}} 占位符的 Markdown 文书，可多次指定")
    ap.add_argument("-o", "--out", default="监理资料/照片匹配", help="输出目录")
    ap.add_argument("--ocr", default="auto", choices=["auto", "rapidocr", "paddleocr", "tesseract", "none"])
    ap.add_argument("--extra-text", help="人工/Agent 识别的照片文字 CSV（列：照片文件,文字），补充或替代 OCR")
    ap.add_argument("--max-per-slot", type=int, default=0, help="每个照片位最多采用几张（0=不限，多余的标为不采用）")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    slots: list[str] = []
    for d in args.doc:
        slots += find_placeholders(Path(d).read_text(encoding="utf-8"))
    slots = list(dict.fromkeys(s for s in slots if "【待填" not in s))
    if not slots:
        print("错误：文书中没有 {{照片:关键字}} 占位符（或仍为【待填】），请先在需要配图的位置插入占位符。", file=sys.stderr)
        return 2

    files = sorted(p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."))
    if not files:
        print(f"错误：{folder} 下没有找到照片（支持 {', '.join(sorted(IMAGE_EXTS))}）。", file=sys.stderr)
        return 2

    extra: dict[str, str] = {}
    if args.extra_text:
        with open(args.extra_text, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                extra[(r.get("照片文件") or "").strip()] = r.get("文字") or ""

    cache_path = out / "ocr缓存.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    engine_name, runner = make_ocr(args.ocr)

    photos = []
    for n, path in enumerate(files, 1):
        rel = path.relative_to(folder).as_posix()
        texts = {"文件名": path.stem, "文件夹": " ".join(path.relative_to(folder).parts[:-1])}
        ocr_text = ""
        if runner:
            sig = file_sig(path)
            if cache.get(rel, {}).get("sig") == sig:
                ocr_text = cache[rel]["text"]
            else:
                print(f"\r识别水印 {n}/{len(files)}：{rel[:40]:<40}", end="", file=sys.stderr, flush=True)
                try:
                    ocr_text = ocr_image(path, runner)
                except Exception as exc:  # noqa: BLE001
                    print(f"\n[警告] OCR 失败 {rel}：{exc}", file=sys.stderr)
                cache[rel] = {"sig": sig, "engine": engine_name, "text": ocr_text}
        texts["水印"] = ocr_text
        manual = extra.get(rel) or extra.get(path.name)
        if manual:
            texts["人工识别"] = manual

        exif = exif_datetime(path)
        wm_dates = find_dates(ocr_text + " " + texts.get("人工识别", ""))
        dates = {"水印": wm_dates, "文件名": find_dates(path.stem + " " + texts["文件夹"]),
                 "EXIF": [exif[:10]] if exif else []}
        if wm_dates:
            tm = TIME_RE.search(re.sub(DATE_SEP, " ", ocr_text))
            shot = wm_dates[0] + (f" {int(tm.group(1)):02d}:{tm.group(2)}" if tm else "")
        else:
            shot = exif or (dates["文件名"][0] if dates["文件名"] else "")
        photos.append({"path": path, "rel": rel, "texts": texts, "dates": dates, "shot": shot})
    if runner:
        print(file=sys.stderr)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    slot_hits: dict[str, list] = {s: [] for s in slots}
    for ph in photos:
        for slot in slots:
            level, why = match_slot(slot, ph)
            if level:
                slot_hits[slot].append((ph, level, why))

    rows, multi = [], {}
    for slot, hits in slot_hits.items():
        hits.sort(key=lambda h: (-LEVELS[h[1]], h[0]["shot"], h[0]["rel"]))
        for k, (ph, level, why) in enumerate(hits):
            use = level in ("高", "中") and (args.max_per_slot <= 0 or k < args.max_per_slot)
            caption = "　".join(x for x in (slot_label(slot), ph["shot"]) if x) or ph["path"].stem
            rows.append({"占位符": slot, "照片路径": str(ph["path"]), "照片文件": ph["rel"], "匹配依据": why,
                         "置信度": level, "拍摄时间": ph["shot"], "图注": caption, "采用": "是" if use else "否"})
            if not is_date_only(slot):
                multi.setdefault(ph["rel"], set()).add(slot)

    map_path = out / "照片匹配表.csv"
    with map_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_FIELDS)
        w.writeheader()
        w.writerows(rows)

    used = {r["照片文件"] for r in rows if r["采用"] == "是"}
    matched = {r["照片文件"] for r in rows}
    empty = [s for s, h in slot_hits.items() if not any(LEVELS[x[1]] >= 2 for x in h)]
    review = [r for r in rows if r["置信度"] == "低"]
    unmatched = [ph for ph in photos if ph["rel"] not in matched]
    ambiguous = {k: v for k, v in multi.items() if len(v) > 1}
    used_per_slot = {s: sum(1 for r in rows if r["占位符"] == s and r["采用"] == "是") for s in slots}
    crowded = {s: n for s, n in used_per_slot.items() if n > 6}

    def tbl(header, data):
        if not data:
            return "无。"
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |" for r in data]
        return "\n".join(lines)

    summary = (f"照片 {len(files)} 张 → 照片位 {len(slots)} 个：已配图 {len(slots) - len(empty)}，缺照片 {len(empty)}，"
               f"待确认 {len(review)}，未匹配照片 {len(unmatched)}，一图多位 {len(ambiguous)}，照片过多 {len(crowded)}；"
               f"共采用照片 {len(used)} 张")
    report = [
        "# 照片匹配报告", "",
        f"- 照片文件夹：`{folder}`",
        f"- 文书：{'、'.join(f'`{Path(d).name}`' for d in args.doc)}",
        f"- 水印识别：{engine_name or '未启用（仅按文件名/文件夹名/EXIF 匹配）'}",
        f"- 结果：{summary}", "",
        "> 如需调整：编辑《照片匹配表.csv》的“采用”（是/否）和“图注”，或新增一行（占位符 + 照片路径 + 采用=是），再重新渲染 DOCX。", "",
        "## 一、缺照片的照片位", "", tbl(["照片位"], [[s] for s in empty]), "",
        "## 二、低置信度匹配（默认不采用，请人工确认）", "",
        tbl(["照片位", "照片文件", "匹配依据"], [[r["占位符"], r["照片文件"], r["匹配依据"]] for r in review]), "",
        "## 三、一张照片匹配多个照片位（请确认是否合理）", "",
        tbl(["照片文件", "照片位"], [[k, "、".join(sorted(v))] for k, v in sorted(ambiguous.items())]), "",
        "## 四、照片过多的照片位（超过 6 张，关键字可能过宽，建议加条件或用 --max-per-slot 限制）", "",
        tbl(["照片位", "采用张数"], [[k, v] for k, v in crowded.items()]), "",
        "## 五、未匹配的照片", "",
        tbl(["照片文件", "日期线索", "识别到的文字（节选）"],
            [[ph["rel"], ph["shot"], (ph["texts"]["水印"] or ph["texts"].get("人工识别", ""))[:60]] for ph in unmatched]),
        "",
    ]
    report_path = out / "照片匹配报告.md"
    report_path.write_text("\n".join(report), encoding="utf-8")

    print(summary)
    print(f"匹配表：{map_path}\n报告：{report_path}")
    return 1 if (empty or review or unmatched or crowded) else 0


if __name__ == "__main__":
    raise SystemExit(main())
