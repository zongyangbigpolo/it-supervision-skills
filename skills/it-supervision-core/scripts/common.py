"""信息监理 skill 公共函数：项目档案读取、金额大写、路径约定。仅依赖标准库。"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PLACEHOLDER = "【待填】"
DEFAULT_ROOT = Path("监理资料")

DOC_TYPES = {
    "GH": ("监理规划", "01-监理规划"),
    "XZ": ("监理实施细则", "01-监理规划"),
    "RZ": ("监理日志", "02-监理日志"),
    "ZB": ("监理周报", "02-监理日志"),
    "YB": ("监理月报", "02-监理日志"),
    "TZ": ("监理通知单", "03-监理通知单"),
    "HF": ("监理通知回复单", "03-监理通知单"),
    "ZT": ("工程暂停令", "03-监理通知单"),
    "FG": ("复工令", "03-监理通知单"),
    "LX": ("监理工作联系单", "03-监理通知单"),
    "YS": ("阶段验收监理意见", "04-阶段验收"),
    "DB": ("等保测评监理检查表", "05-等保测评检查"),
    "ZG": ("等保整改跟踪表", "05-等保测评检查"),
    "DH": ("硬件设备到货验收单", "06-到货验收"),
    "HY": ("会议纪要", "07-会议纪要"),
}


def read_profile_scalar(profile: Path, key: str) -> str | None:
    """从项目档案.yaml 读取顶层标量（避免依赖 PyYAML）。"""
    if not profile.exists():
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*:\s*(.*?)\s*(#.*)?$")
    for line in profile.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            value = m.group(1).strip().strip("'\"")
            return value or None
    return None


_DIGITS = "零壹贰叁肆伍陆柒捌玖"
_UNITS = ["", "拾", "佰", "仟"]
_SECTIONS = ["", "万", "亿", "万亿"]


def _four_digits(n: int) -> str:
    out, zero = "", False
    for i in range(3, -1, -1):
        d = n // (10**i) % 10
        if d == 0:
            zero = bool(out)
        else:
            if zero:
                out += "零"
                zero = False
            out += _DIGITS[d] + _UNITS[i]
    return out


def amount_to_chinese(amount: float | str | Decimal) -> str:
    """金额转人民币大写，例：123400 -> 壹拾贰万叁仟肆佰元整。"""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value < 0:
        return "负" + amount_to_chinese(-value)
    integer = int(value)
    fen_total = int((value - integer) * 100)
    jiao, fen = divmod(fen_total, 10)

    if integer == 0:
        int_str = "零"
    else:
        segs = []
        n = integer
        while n:
            segs.append(n % 10000)
            n //= 10000
        int_str, pending_zero = "", False
        for idx in range(len(segs) - 1, -1, -1):
            seg = segs[idx]
            if seg == 0:
                pending_zero = bool(int_str)
                continue
            if int_str and (pending_zero or seg < 1000):
                int_str += "零"
            int_str += _four_digits(seg) + _SECTIONS[idx]
            pending_zero = False
    if jiao == 0 and fen == 0:
        return int_str + "元整"
    result = int_str + "元" if integer else ""
    if jiao:
        result += _DIGITS[jiao] + "角"
    elif integer:
        result += "零"
    if fen:
        result += _DIGITS[fen] + "分"
    else:
        result += "整"
    return result


def format_amount(amount: float | str | Decimal) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"人民币{amount_to_chinese(value)}（¥{value:,.2f}）"


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        print(format_amount(arg))
