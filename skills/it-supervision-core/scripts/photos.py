"""现场照片占位符与插图（供 md_to_docx.py 与 photo_match.py 共用）。

占位符语法（可写在段落、列表项、表格单元格中）：
  {{照片:SN-A0003}}                 含该关键字的照片（序列号、设备编号等）
  {{照片:SN-A0003|FW-01}}           任一关键字命中即可（或）
  {{照片:SN-A0003&加电}}            所有关键字都要命中（且）
  {{照片:日期=2026-11-26}}          按拍摄日期匹配（文件名/水印/EXIF 任一）
  {{照片:日期=2026-11-26&服务器}}   组合条件
也可写作 {{photo:...}}。
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

PHOTO_RE = re.compile(r"\{\{\s*(?:照片|photo)\s*[:：]\s*([^{}]+?)\s*\}\}")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".heif"}
MAP_FIELDS = ["占位符", "照片路径", "照片文件", "匹配依据", "置信度", "拍摄时间", "图注", "采用"]

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = ImageOps = None
else:
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass


def find_placeholders(text: str) -> list[str]:
    return [m.group(1).replace("\\|", "|").strip() for m in PHOTO_RE.finditer(text)]


def strip_placeholders(text: str) -> str:
    return PHOTO_RE.sub("", text).strip()


def load_photo_map(csv_path: Path) -> dict[str, list[tuple[Path, str]]]:
    """读取照片匹配表，返回 {占位符: [(路径, 图注)]}，仅取“采用=是”的行。"""
    result: dict[str, list[tuple[Path, str]]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("采用") or "是").strip() not in ("是", "Y", "y", "yes", "1"):
                continue
            key = (row.get("占位符") or "").strip()
            path = Path((row.get("照片路径") or "").strip())
            if not path.is_absolute():
                path = (csv_path.parent / path).resolve()
            if key and path.name:
                result.setdefault(key, []).append((path, (row.get("图注") or "").strip()))
    return result


def prepare_image(path: Path, max_px: int = 1600, quality: int = 82):
    """按 EXIF 方向校正、缩放、压缩。返回 (文件流或路径, 宽高比 w/h 或 None)。"""
    if Image is None:
        return str(path), None
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)
        return buf, im.width / im.height


def fit_size(aspect: float | None, max_w_cm: float, max_h_cm: float) -> tuple[float, float | None]:
    if not aspect:
        return max_w_cm, None
    w = min(max_w_cm, max_h_cm * aspect)
    return w, w / aspect
