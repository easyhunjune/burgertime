"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""
import re
from decimal import Decimal

UNITS = [("w", 604800), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]
_ORDER = {u: i for i, (u, _) in enumerate(UNITS)}
_SIZE = dict(UNITS)
_COMPONENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z])")
_DIGITS = "0123456789"


def parse_duration(text):
    if not isinstance(text, str):
        raise TypeError("text must be str")
    s = text.strip()
    if s in ("0", "-0"):
        return 0
    sign = 1
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    if not s or s[0] not in _DIGITS:
        raise ValueError(f"invalid duration: {text!r}")
    pos, total, last, seen_fraction = 0, Decimal(0), -1, False
    while pos < len(s):
        if pos > 0:
            while pos < len(s) and s[pos] == " ":
                pos += 1
        m = _COMPONENT.match(s, pos)
        if not m:
            raise ValueError(f"invalid duration: {text!r}")
        number, unit = m.group(1), m.group(2).lower()
        if unit not in _SIZE or _ORDER[unit] <= last or seen_fraction:
            raise ValueError(f"invalid duration: {text!r}")
        seen_fraction = "." in number
        total += Decimal(number) * _SIZE[unit]
        last, pos = _ORDER[unit], m.end()
    if total != total.to_integral_value():
        raise ValueError(f"not a whole number of seconds: {text!r}")
    return sign * int(total)


def format_duration(seconds):
    if isinstance(seconds, bool) or not isinstance(seconds, int):
        raise TypeError("seconds must be int")
    if seconds == 0:
        return "0s"
    rest, parts = abs(seconds), []
    for unit, size in UNITS:
        count, rest = divmod(rest, size)
        if count:
            parts.append(f"{count}{unit}")
    return ("-" if seconds < 0 else "") + "".join(parts)
