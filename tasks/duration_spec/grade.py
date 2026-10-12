import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("duration")

VALID = [
    ("parse_basic", "1h30m", 5400),
    ("parse_all_units", "1w2d3h4m5s", 788645),
    ("parse_space_between", "1h 30m", 5400),
    ("parse_trim_and_multi_space", "  2d   5m  ", 173100),
    ("parse_uppercase", "1H30M", 5400),
    ("parse_leading_zeros", "007s", 7),
    ("parse_bare_zero", "0", 0),
    ("parse_negative_zero", "-0", 0),
    ("parse_negative", "-1h30m", -5400),
    ("parse_fraction_last", "1h1.5m", 3690),
    ("parse_fraction_only", "1.5h", 5400),
    ("parse_fraction_day", "0.25d", 21600),
    ("parse_large", "100w", 60480000),
    ("parse_zero_components", "0h0m", 0),
]
for _name, _text, _want in VALID:
    g.case(_name)(lambda m, ws, text=_text, want=_want: equal(m.parse_duration(text), want))

INVALID = [
    ("invalid_empty", ""),
    ("invalid_blank", "   "),
    ("invalid_unitless", "5"),
    ("invalid_trailing_unitless", "1h30"),
    ("invalid_space_inside_component", "1 h"),
    ("invalid_order", "1m1h"),
    ("invalid_duplicate_unit", "1h1h"),
    ("invalid_unknown_unit", "1y"),
    ("invalid_plus_sign", "+1h"),
    ("invalid_space_after_sign", "- 1h"),
    ("invalid_double_sign", "--1h"),
    ("invalid_lone_minus", "-"),
    ("invalid_fraction_not_last", "1.5h30m"),
    ("invalid_fraction_subsecond", "0.5s"),
    ("invalid_fraction_inexact", "1.01m"),
    ("invalid_fraction_leading_dot", ".5h"),
    ("invalid_fraction_trailing_dot", "1.h"),
    ("invalid_tab_separator", "1h\t30m"),
    ("invalid_non_ascii_digit", "١h"),
    ("invalid_comma_separator", "1h,30m"),
]
for _name, _text in INVALID:
    g.case(_name)(lambda m, ws, text=_text: raises(ValueError, m.parse_duration, text))

g.case("parse_type_int")(lambda m, ws: raises(TypeError, m.parse_duration, 5))
g.case("parse_type_bytes")(lambda m, ws: raises(TypeError, m.parse_duration, b"1h"))

FORMAT = [
    ("format_zero", 0, "0s"),
    ("format_mixed", 90061, "1d1h1m1s"),
    ("format_hour", 3600, "1h"),
    ("format_week", 604800, "1w"),
    ("format_all_units", 694861, "1w1d1h1m1s"),
    ("format_negative", -90, "-1m30s"),
    ("format_seconds_only", 59, "59s"),
]
for _name, _n, _want in FORMAT:
    g.case(_name)(lambda m, ws, n=_n, want=_want: equal(m.format_duration(n), want))

g.case("format_type_bool")(lambda m, ws: raises(TypeError, m.format_duration, True))
g.case("format_type_float")(lambda m, ws: raises(TypeError, m.format_duration, 1.0))


@g.case("roundtrip")
def _roundtrip(m, ws):
    for n in (-1000000, -1, 1, 59, 61, 3601, 86399, 90061, 10**9):
        equal(m.parse_duration(m.format_duration(n)), n)


if __name__ == "__main__":
    g.main()
