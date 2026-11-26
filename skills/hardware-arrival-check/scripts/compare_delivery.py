#!/usr/bin/env python3
"""合同设备清单 vs 到货清单 自动比对，输出 Markdown 比对结果（可直接粘贴进到货验收单）。

用法：
  python3 compare_delivery.py 合同设备清单.csv 本批到货清单.csv [--previous 第1批.csv ...] [-o 比对结果.md]
                              [--detail] [--photo-slots]   # 附设备序列号明细表；--photo-slots 加“现场照片”列

合同清单列：合同项号, 设备名称, 品牌, 型号, 主要配置, 单位, 数量, 单价
到货清单列：序号, 合同项号, 设备名称, 品牌, 型号, 序列号, 外观, 加电, 备注（每台一行）
支持 .csv（UTF-8/UTF-8-BOM/GBK）与 .xlsx（需 openpyxl）。
退出码：0 无差异；1 存在差异或问题（便于 agent 判断）。
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

CORE_SCRIPTS = Path(__file__).resolve().parents[2] / "it-supervision-core" / "scripts"
sys.path.insert(0, str(CORE_SCRIPTS))
try:
    from common import format_amount  # noqa: E402
except ImportError:  # 单独安装本 skill 时降级
    def format_amount(v):  # type: ignore
        return f"¥{Decimal(str(v)):,.2f}"


def load_rows(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            sys.exit("读取 xlsx 需要 openpyxl：pip install openpyxl；或另存为 CSV。")
        ws = load_workbook(path, read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(it)]
        return [{header[i]: ("" if v is None else str(v).strip()) for i, v in enumerate(r) if i < len(header)}
                for r in it if any(v not in (None, "") for v in r)]
    for enc in ("utf-8-sig", "gbk"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)
                        if any((v or "").strip() for v in r.values())]
        except UnicodeDecodeError:
            continue
    sys.exit(f"无法识别编码：{path}")


def norm(s: str) -> str:
    return "".join(s.split()).upper()


def to_dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", "").replace("，", "").replace("¥", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def md_table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="到货比对")
    ap.add_argument("contract")
    ap.add_argument("delivery")
    ap.add_argument("--previous", nargs="*", default=[], help="此前批次到货清单（计算累计）")
    ap.add_argument("-o", "--output")
    ap.add_argument("--detail", action="store_true", help="附“设备序列号明细”表")
    ap.add_argument("--photo-slots", action="store_true", help="明细表加“现场照片”列（{{照片:序列号}} 占位符，供 photo_match.py 配图）")
    args = ap.parse_args()

    contract = load_rows(Path(args.contract))
    current = load_rows(Path(args.delivery))
    previous = [r for p in args.previous for r in load_rows(Path(p))]

    citems = {r.get("合同项号", str(i + 1)): r for i, r in enumerate(contract)}
    by_model = {(norm(r.get("品牌", "")), norm(r.get("型号", ""))): k for k, r in citems.items()}

    def item_of(r: dict[str, str]) -> str | None:
        k = r.get("合同项号", "")
        if k in citems:
            return k
        return by_model.get((norm(r.get("品牌", "")), norm(r.get("型号", ""))))

    cur_cnt, prev_cnt = Counter(), Counter()
    mismatches, extras, no_sn, bad_state = [], [], [], []
    for r in previous:
        k = item_of(r)
        if k:
            prev_cnt[k] += 1
    for idx, r in enumerate(current, 1):
        k = item_of(r)
        row_id = r.get("序号") or str(idx)
        if not k:
            extras.append([row_id, r.get("设备名称", ""), r.get("品牌", ""), r.get("型号", ""), r.get("序列号", "")])
            continue
        cur_cnt[k] += 1
        c = citems[k]
        for field in ("品牌", "型号"):
            if r.get(field) and c.get(field) and norm(r[field]) != norm(c[field]):
                mismatches.append([row_id, k, field, c[field], r[field], r.get("序列号", "")])
        if not r.get("序列号"):
            no_sn.append([row_id, k, r.get("设备名称", "") or c.get("设备名称", "")])
        for field, ok in (("外观", "合格"), ("加电", "正常")):
            v = r.get(field, "")
            if v and v not in (ok, "不适用"):
                bad_state.append([row_id, k, r.get("序列号", ""), field, v, r.get("备注", "")])

    sn_all = [norm(r.get("序列号", "")) for r in previous + current if r.get("序列号")]
    sn_cur: dict[str, list[str]] = defaultdict(list)
    for idx, r in enumerate(current, 1):
        if r.get("序列号"):
            sn_cur[norm(r["序列号"])].append(r.get("序号") or str(idx))
    dup_sn = sorted(s for s, n in Counter(sn_all).items() if n > 1 and s in sn_cur)

    summary, total, over = [], Decimal(0), []
    for k, c in citems.items():
        need = to_dec(c.get("数量", "")) or Decimal(0)
        now, cum = cur_cnt[k], cur_cnt[k] + prev_cnt[k]
        diff = cum - need
        price = to_dec(c.get("单价", ""))
        amount = price * now if price is not None else None
        if amount is not None:
            total += amount
        if diff > 0:
            over.append(k)
        diff_s = "一致" if diff == 0 else (f"超出 {diff}" if diff > 0 else f"尚缺 {-diff}")
        bad_models = len({m[0] for m in mismatches if m[1] == k})
        if bad_models:
            diff_s += f"（本批含型号不符 {bad_models} 台）"
        summary.append([k, c.get("设备名称", ""), f"{c.get('品牌', '')} {c.get('型号', '')}".strip(), f"{need.normalize():f}",
                        str(now), str(cum), diff_s, c.get("单价", "") or "【待填】",
                        f"{amount:,.2f}" if amount is not None else "【待填】"])

    parts = ["# 到货比对结果", "",
             f"- 合同清单：`{Path(args.contract).name}`（{len(citems)} 项）",
             f"- 本批到货：`{Path(args.delivery).name}`（{len(current)} 台/套）",
             f"- 此前批次：{len(previous)} 台/套", "",
             "## 一、到货汇总（按合同项）", "",
             md_table(["合同项号", "设备名称", "品牌型号", "合同数量", "本批实到", "累计实到", "差异", "合同单价（元）", "本批金额（元）"], summary),
             "", f"本批到货金额合计（按合同单价）：{format_amount(total)}" if total else "本批到货金额合计：【待填：合同单价缺失】", ""]

    def section(title: str, header: list[str], rows: list[list[str]]) -> None:
        parts.extend([f"## {title}", ""])
        parts.append(md_table(header, rows) if rows else "无。")
        parts.append("")

    section("二、品牌/型号与合同不一致", ["到货序号", "合同项号", "字段", "合同要求", "实到", "序列号"], mismatches)
    section("三、重复序列号（含与此前批次重复）", ["序列号", "本批到货序号"], [[s, "、".join(sn_cur[s])] for s in dup_sn])
    section("四、缺少序列号", ["到货序号", "合同项号", "设备名称"], no_sn)
    section("五、合同外设备（无法匹配合同项）", ["到货序号", "设备名称", "品牌", "型号", "序列号"], extras)
    section("六、外观/加电异常", ["到货序号", "合同项号", "序列号", "检查项", "结果", "备注"], bad_state)

    if args.detail or args.photo_slots:
        header = ["序号", "合同项号", "设备名称", "品牌", "型号", "序列号（SN）", "外观", "加电", "备注"]
        detail = []
        for idx, r in enumerate(current, 1):
            row = [r.get("序号") or str(idx), item_of(r) or "合同外", r.get("设备名称", ""), r.get("品牌", ""),
                   r.get("型号", ""), r.get("序列号", "") or "【待填】", r.get("外观", ""), r.get("加电", ""), r.get("备注", "")]
            if args.photo_slots:
                row.append("{{照片:" + r["序列号"].strip() + "}}" if r.get("序列号") else "")
            detail.append(row)
        if args.photo_slots:
            header.append("现场照片")
        section("附件：设备序列号明细", header, detail)

    issues = len(mismatches) + len(dup_sn) + len(no_sn) + len(extras) + len(bad_state) + len(over)
    parts.append(f"> 自动比对发现问题 {issues} 项（累计超合同数量 {len(over)} 项）。比对仅基于清单数据，"
                 "实物铭牌、配置、证明文件仍须现场核查。")
    text = "\n".join(parts) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"已生成：{args.output}（问题 {issues} 项）")
    else:
        print(text)
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
