"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""
import calendar
import datetime as dt
import re

HORIZON_DAYS = 1500
_MONTHS = {n: i for i, n in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_DAYS = {n: i for i, n in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}
_MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *",
}
_DIGITS = re.compile(r"[0-9]+")

# (lo, hi, largest value covered by *, names)
_FIELDS = [(0, 59, 59, None), (0, 23, 23, None), (1, 31, 31, None), (1, 12, 12, _MONTHS), (0, 7, 6, _DAYS)]


def _number(tok, lo, hi, names):
    if names and tok.upper() in names:
        return names[tok.upper()]
    if not _DIGITS.fullmatch(tok):
        raise ValueError(f"bad value {tok!r}")
    value = int(tok)
    if not lo <= value <= hi:
        raise ValueError(f"value {value} out of range")
    return value


def _plain(item, lo, hi, star_hi, names):
    base, slash, step_text = item.partition("/")
    step = 1
    if slash:
        if not _DIGITS.fullmatch(step_text) or int(step_text) < 1:
            raise ValueError(f"bad step in {item!r}")
        step = int(step_text)
    if base == "*":
        start, end = lo, star_hi
    elif "-" in base:
        a, b = base.split("-", 1)
        start, end = _number(a, lo, hi, names), _number(b, lo, hi, names)
        if start > end:
            raise ValueError(f"reversed range {item!r}")
    else:
        start = _number(base, lo, hi, names)
        end = star_hi if slash else start
        if slash and start > end:
            raise ValueError(f"empty range {item!r}")
    return set(range(start, end + 1, step))


class _Field:
    def __init__(self, text, index):
        lo, hi, star_hi, names = _FIELDS[index]
        self.star = text.startswith("*")
        self.values = set()
        self.last = self.last_weekday = False
        self.nearest = set()      # nW
        self.last_dow = set()     # nL
        self.nth_dow = set()      # (n, k)
        for item in text.split(","):
            if not item:
                raise ValueError("empty item")
            if index == 2 and item.upper() == "L":
                self.last = True
            elif index == 2 and item.upper() == "LW":
                self.last_weekday = True
            elif index == 2 and item[-1:].upper() == "W":
                self.nearest.add(_number(item[:-1], 1, 31, None))
            elif index == 4 and item[-1:].upper() == "L":
                self.last_dow.add(_number(item[:-1], 0, 7, None) % 7)
            elif index == 4 and "#" in item:
                n, k = item.split("#", 1)
                self.nth_dow.add((_number(n, 0, 7, None) % 7, _number(k, 1, 5, None)))
            else:
                values = _plain(item, lo, hi, star_hi, names)
                if index == 4:
                    values = {v % 7 for v in values}
                self.values |= values


def _cron_dow(day):
    return (day.weekday() + 1) % 7


def _nearest_weekday(year, month, n):
    last = calendar.monthrange(year, month)[1]
    if n > last:
        return None
    wd = dt.date(year, month, n).weekday()
    if wd == 5:
        return n + 2 if n == 1 else n - 1
    if wd == 6:
        return n - 2 if n == last else n + 1
    return n


def _dom_matches(field, day):
    if day.day in field.values:
        return True
    last = calendar.monthrange(day.year, day.month)[1]
    if field.last and day.day == last:
        return True
    if field.last_weekday:
        lw = last
        while dt.date(day.year, day.month, lw).weekday() >= 5:
            lw -= 1
        if day.day == lw:
            return True
    return any(_nearest_weekday(day.year, day.month, n) == day.day for n in field.nearest)


def _dow_matches(field, day):
    dow = _cron_dow(day)
    if dow in field.values:
        return True
    last = calendar.monthrange(day.year, day.month)[1]
    if dow in field.last_dow and day.day + 7 > last:
        return True
    return (dow, (day.day - 1) // 7 + 1) in field.nth_dow


def _parse(expr):
    text = _MACROS.get(expr.strip(), expr)
    parts = text.split()
    if len(parts) != 5:
        raise ValueError("expected 5 fields")
    return [_Field(p, i) for i, p in enumerate(parts)]


def next_fire(expr, after):
    if not isinstance(expr, str):
        raise TypeError("expr must be str")
    if not isinstance(after, dt.datetime):
        raise TypeError("after must be datetime")
    if after.tzinfo is not None:
        raise ValueError("after must be naive")
    minute, hour, dom, month, dow = _parse(expr)
    start = after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    for offset in range(HORIZON_DAYS + 1):
        day = start.date() + dt.timedelta(days=offset)
        if day.month not in month.values:
            continue
        dom_ok, dow_ok = _dom_matches(dom, day), _dow_matches(dow, day)
        if not ((dom_ok and dow_ok) if (dom.star or dow.star) else (dom_ok or dow_ok)):
            continue
        for h in sorted(hour.values):
            for m in sorted(minute.values):
                candidate = dt.datetime(day.year, day.month, day.day, h, m)
                if candidate >= start:
                    return candidate
    raise ValueError("no matching time within the horizon")
