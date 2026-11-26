#!/usr/bin/env python3
"""分配下一个监理文书编号，并登记到 监理资料/编号台账.csv。

用法：
  python3 next_doc_no.py --type TZ [--title "关于XX的整改通知"] [--root 监理资料] [--year 2026] [--dry-run]
输出：编号（stdout 第一行）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_ROOT, DOC_TYPES, PLACEHOLDER, read_profile_scalar  # noqa: E402

FIELDS = ["编号", "类型码", "文书类型", "标题", "登记日期"]


def main() -> int:
    ap = argparse.ArgumentParser(description="分配监理文书编号")
    ap.add_argument("--type", required=True, choices=sorted(DOC_TYPES), help="类型码")
    ap.add_argument("--title", default="", help="文书标题（登记用）")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="监理资料根目录")
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--abbr", help="项目简称（默认读取项目档案）")
    ap.add_argument("--dry-run", action="store_true", help="只显示不登记")
    args = ap.parse_args()

    root = Path(args.root)
    profile = root / "项目档案.yaml"
    abbr = args.abbr or read_profile_scalar(profile, "项目简称")
    prefix = read_profile_scalar(profile, "编号前缀") or "JL"
    if not abbr or abbr == PLACEHOLDER:
        print(f"错误：未找到项目简称，请先在 {profile} 中填写“项目简称”，或使用 --abbr 指定。", file=sys.stderr)
        return 2

    ledger = root / "编号台账.csv"
    rows: list[dict[str, str]] = []
    if ledger.exists():
        with ledger.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

    stem = f"{prefix}-{abbr}-{args.type}-{args.year}-"
    used = [int(r["编号"][len(stem):]) for r in rows if r.get("编号", "").startswith(stem) and r["编号"][len(stem):].isdigit()]
    number = f"{stem}{(max(used) if used else 0) + 1:03d}"
    print(number)

    if not args.dry_run:
        root.mkdir(parents=True, exist_ok=True)
        new_file = not ledger.exists()
        with ledger.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new_file:
                w.writeheader()
            w.writerow({"编号": number, "类型码": args.type, "文书类型": DOC_TYPES[args.type][0],
                        "标题": args.title, "登记日期": dt.date.today().isoformat()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
