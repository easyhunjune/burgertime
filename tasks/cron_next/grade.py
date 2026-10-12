import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("cronnext")
D = datetime.datetime

# (name, expr, after, expected) — 독립 무차별 대입과 대조해 만든 값
VALID = [
    ('basic', '30 9 * * *', datetime.datetime(2026, 3, 10, 8, 0), datetime.datetime(2026, 3, 10, 9, 30)),
    ('strictly_after', '30 9 * * *', datetime.datetime(2026, 3, 10, 9, 30), datetime.datetime(2026, 3, 11, 9, 30)),
    ('seconds_floor', '* * * * *', datetime.datetime(2026, 3, 10, 9, 30, 45), datetime.datetime(2026, 3, 10, 9, 31)),
    ('minute_step_hour_rollover', '*/15 * * * *', datetime.datetime(2026, 3, 10, 10, 45), datetime.datetime(2026, 3, 10, 11, 0)),
    ('range_step', '10-40/10 8 * * *', datetime.datetime(2026, 3, 10, 8, 35), datetime.datetime(2026, 3, 10, 8, 40)),
    ('range_step_next_day', '10-40/10 8 * * *', datetime.datetime(2026, 3, 10, 8, 41), datetime.datetime(2026, 3, 11, 8, 10)),
    ('slash_shorthand', '50/5 * * * *', datetime.datetime(2026, 3, 10, 10, 56), datetime.datetime(2026, 3, 10, 11, 50)),
    ('list_hours', '0,30 9-10 * * *', datetime.datetime(2026, 3, 10, 9, 45), datetime.datetime(2026, 3, 10, 10, 0)),
    ('hour_step', '0 */6 * * *', datetime.datetime(2026, 3, 10, 13, 0), datetime.datetime(2026, 3, 10, 18, 0)),
    ('month_names_wrap_year', '0 12 1 jan,JUL *', datetime.datetime(2026, 8, 1, 0, 0), datetime.datetime(2027, 1, 1, 12, 0)),
    ('month_range_step_names', '0 0 1 JAN-DEC/3 *', datetime.datetime(2026, 2, 1, 0, 0), datetime.datetime(2026, 4, 1, 0, 0)),
    ('dow_names_range', '0 9 * * MON-FRI', datetime.datetime(2026, 3, 14, 10, 0), datetime.datetime(2026, 3, 16, 9, 0)),
    ('dow_lowercase_name', '0 9 * * sat', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 14, 9, 0)),
    ('dow_seven_is_sunday', '0 0 * * 7', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 15, 0, 0)),
    ('dow_range_to_seven', '0 0 * * 5-7', datetime.datetime(2026, 3, 14, 0, 0), datetime.datetime(2026, 3, 15, 0, 0)),
    ('dow_star_step', '0 0 * * */2', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 12, 0, 0)),
    ('dow_range_step_seven', '0 0 * * 1-7/3', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 12, 0, 0)),
    ('or_semantics_friday', '0 0 13 * 5', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 3, 6, 0, 0)),
    ('or_semantics_13th', '0 0 13 * 1', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 13, 0, 0)),
    ('and_with_star_step_dom', '0 0 */2 * 1', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 3, 9, 0, 0)),
    ('and_with_star_step_dow', '0 0 1 * */7', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 11, 1, 0, 0)),
    ('dom_L_feb', '0 0 L * *', datetime.datetime(2026, 2, 10, 0, 0), datetime.datetime(2026, 2, 28, 0, 0)),
    ('dom_L_leap', '0 0 L 2 *', datetime.datetime(2027, 3, 1, 0, 0), datetime.datetime(2028, 2, 29, 0, 0)),
    ('dom_L_list', '0 0 1,L * *', datetime.datetime(2026, 4, 2, 0, 0), datetime.datetime(2026, 4, 30, 0, 0)),
    ('dom_LW_last_sunday', '0 0 LW * *', datetime.datetime(2026, 5, 20, 0, 0), datetime.datetime(2026, 5, 29, 0, 0)),
    ('dom_LW_last_saturday', '0 0 LW * *', datetime.datetime(2026, 10, 20, 0, 0), datetime.datetime(2026, 10, 30, 0, 0)),
    ('W_first_saturday', '0 0 1W * *', datetime.datetime(2026, 7, 20, 0, 0), datetime.datetime(2026, 8, 3, 0, 0)),
    ('W_saturday_mid', '0 0 15W * *', datetime.datetime(2026, 8, 2, 0, 0), datetime.datetime(2026, 8, 14, 0, 0)),
    ('W_sunday_mid', '0 0 15W * *', datetime.datetime(2026, 11, 2, 0, 0), datetime.datetime(2026, 11, 16, 0, 0)),
    ('W_first_sunday', '0 0 1W * *', datetime.datetime(2026, 2, 20, 0, 0), datetime.datetime(2026, 3, 2, 0, 0)),
    ('W_last_sunday', '0 0 30W * *', datetime.datetime(2028, 4, 2, 0, 0), datetime.datetime(2028, 4, 28, 0, 0)),
    ('W_beyond_month', '0 0 31W * *', datetime.datetime(2026, 4, 1, 0, 0), datetime.datetime(2026, 5, 29, 0, 0)),
    ('dow_last_friday', '0 0 * * 5L', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 3, 27, 0, 0)),
    ('dow_nth', '0 0 * * 3#2', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 3, 11, 0, 0)),
    ('dow_fifth_monday', '0 0 * * 1#5', datetime.datetime(2026, 4, 1, 0, 0), datetime.datetime(2026, 6, 29, 0, 0)),
    ('dow_first_sunday_as_seven', '0 0 * * 7#1', datetime.datetime(2026, 3, 2, 0, 0), datetime.datetime(2026, 4, 5, 0, 0)),
    ('dom_L_or_monday', '0 0 L * 1', datetime.datetime(2026, 3, 24, 0, 0), datetime.datetime(2026, 3, 30, 0, 0)),
    ('dom_15_or_last_friday', '0 0 15 * 5L', datetime.datetime(2026, 3, 16, 0, 0), datetime.datetime(2026, 3, 27, 0, 0)),
    ('star_dom_with_nth', '0 0 * * 5#3', datetime.datetime(2026, 3, 1, 0, 0), datetime.datetime(2026, 3, 20, 0, 0)),
    ('leap_day', '0 0 29 2 *', datetime.datetime(2025, 3, 1, 0, 0), datetime.datetime(2028, 2, 29, 0, 0)),
    ('year_rollover', '59 23 31 12 *', datetime.datetime(2026, 12, 31, 23, 59), datetime.datetime(2027, 12, 31, 23, 59)),
    ('new_year', '0 0 1 1 *', datetime.datetime(2026, 12, 31, 23, 59, 59), datetime.datetime(2027, 1, 1, 0, 0)),
    ('whitespace', ' 0  0\t* *   *  ', datetime.datetime(2026, 3, 10, 5, 0), datetime.datetime(2026, 3, 11, 0, 0)),
    ('macro_daily', '@daily', datetime.datetime(2026, 3, 10, 5, 0), datetime.datetime(2026, 3, 11, 0, 0)),
    ('macro_hourly', '@hourly', datetime.datetime(2026, 3, 10, 5, 0), datetime.datetime(2026, 3, 10, 6, 0)),
    ('macro_weekly', '@weekly', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 3, 15, 0, 0)),
    ('macro_yearly', '@yearly', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2027, 1, 1, 0, 0)),
    ('macro_monthly', '@monthly', datetime.datetime(2026, 3, 10, 0, 0), datetime.datetime(2026, 4, 1, 0, 0)),
]
for _name, _expr, _after, _want in VALID:
    g.case(_name)(lambda m, ws, e=_expr, a=_after, w=_want: equal(m.next_fire(e, a), w))

# 잘못된 식과 1500일 안에 맞는 시각이 없는 식은 ValueError
INVALID = [
    ('err_four_fields', '0 0 * *'),
    ('err_six_fields', '0 0 * * * *'),
    ('err_minute_60', '60 * * * *'),
    ('err_hour_24', '0 24 * * *'),
    ('err_dom_0', '0 0 0 * *'),
    ('err_month_13', '0 0 1 13 *'),
    ('err_dow_8', '0 0 * * 8'),
    ('err_reversed_range', '10-5 * * * *'),
    ('err_step_zero', '*/0 * * * *'),
    ('err_empty_item', '1,,2 * * * *'),
    ('err_trailing_comma', '1, * * * *'),
    ('err_L_in_minute', 'L * * * *'),
    ('err_W_in_dow', '0 0 * * 1W'),
    ('err_hash_in_dom', '0 0 1#2 * *'),
    ('err_nth_k_6', '0 0 * * 5#6'),
    ('err_nth_k_0', '0 0 * * 5#0'),
    ('err_W_32', '0 0 32W * *'),
    ('err_L_in_month', '0 0 1 L *'),
    ('err_unknown_name', '0 0 * * FUNDAY'),
    ('err_question_mark', '0 0 ? * *'),
    ('err_plus_sign', '+5 * * * *'),
    ('err_negative', '-1 * * * *'),
    ('err_name_in_nth', '0 0 * * FRI#2'),
    ('err_empty', ''),
    ('horizon_feb_30', '0 0 30 2 *'),
    ('horizon_apr_31', '0 0 31 4 *'),
    ('horizon_short_months_31', '0 0 31 2,4,6,9,11 *'),
]
for _name, _expr in INVALID:
    g.case(_name)(lambda m, ws, e=_expr: raises(ValueError, m.next_fire, e, D(2026, 3, 10)))

g.case("type_expr_not_str")(lambda m, ws: raises(TypeError, m.next_fire, 5, D(2026, 3, 10)))
g.case("type_after_date")(lambda m, ws: raises(TypeError, m.next_fire, "* * * * *", datetime.date(2026, 3, 10)))
g.case("type_after_str")(lambda m, ws: raises(TypeError, m.next_fire, "* * * * *", "2026-03-10"))
g.case("aware_after")(lambda m, ws: raises(
    ValueError, m.next_fire, "* * * * *", D(2026, 3, 10, tzinfo=datetime.timezone.utc)))


@g.case("result_is_naive_and_whole_minute")
def _whole_minute(m, ws):
    r = m.next_fire("*/7 * * * *", D(2026, 3, 10, 9, 0, 59, 999999))
    equal((r.tzinfo, r.second, r.microsecond), (None, 0, 0))
    equal(r, D(2026, 3, 10, 9, 7))


if __name__ == "__main__":
    g.main()
