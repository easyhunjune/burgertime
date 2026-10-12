import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("sheet")


def make(m, cells):
    s = m.Sheet()
    for name, raw in cells.items():
        s.set(name, raw)
    return s


# (case name, cells to set, cell to read, expected value)
SIMPLE = [
    ("literal_int", {"A1": "42"}, "A1", 42),
    ("literal_negative", {"A1": "-7"}, "A1", -7),
    ("literal_string_space", {"A1": " 5"}, "A1", " 5"),
    ("literal_string_decimal", {"A1": "1.5"}, "A1", "1.5"),
    ("empty_unset", {}, "C3", None),
    ("precedence", {"A1": "=1+2*3"}, "A1", 7),
    ("parentheses", {"A1": "=(1+2)*3"}, "A1", 9),
    ("trunc_div_negative_left", {"A1": "=-7/2"}, "A1", -3),
    ("trunc_div_negative_right", {"A1": "=7/-2"}, "A1", -3),
    ("div_zero", {"A1": "=1/0"}, "A1", "#DIV/0!"),
    ("ref_chain", {"A1": "2", "B1": "=A1*3", "C1": "=B1+A1"}, "C1", 8),
    ("empty_ref_is_zero", {"A1": "=Z9+1"}, "A1", 1),
    ("string_arithmetic", {"A1": "abc", "B1": "=A1+1"}, "B1", "#VALUE!"),
    ("string_unary_minus", {"A1": "abc", "B1": "=-A1"}, "B1", "#VALUE!"),
    ("string_passthrough", {"A1": "abc", "B1": "=A1"}, "B1", "abc"),
    ("string_equality", {"A1": "x", "A2": "x", "B1": "=A1=A2"}, "B1", 1),
    ("number_vs_string_equal", {"A1": "5", "A2": " 5", "B1": "=A1=A2"}, "B1", 0),
    ("number_vs_string_not_equal", {"A1": "5", "A2": " 5", "B1": "=A1<>A2"}, "B1", 1),
    ("number_vs_string_order", {"A1": "5", "A2": " 5", "B1": "=A1<A2"}, "B1", "#VALUE!"),
    ("string_order", {"A1": "apple", "A2": "banana", "B1": "=A1<A2"}, "B1", 1),
    ("string_order_le", {"A1": "apple", "A2": "banana", "B1": "=A2<=A1"}, "B1", 0),
    ("comparison_below_addition", {"A1": "=1+1=2"}, "A1", 1),
    ("comparison_below_multiplication", {"A1": "=2*3>5"}, "A1", 1),
    ("comparison_non_associative", {"A1": "=1<2<3"}, "A1", "#PARSE!"),
    ("comparison_in_arithmetic", {"A1": "=(1<2)*10"}, "A1", 10),
    ("double_unary", {"A1": "=--3"}, "A1", 3),
    ("unary_after_operator", {"A1": "=2*-3"}, "A1", -6),
    ("unary_then_subtract", {"A1": "=-2-3"}, "A1", -5),
    ("empty_equals_zero", {"A1": "=Z1=0"}, "A1", 1),
    ("big_integers", {"A1": "=99999999999999999999*99999999999999999999"}, "A1",
     99999999999999999999 * 99999999999999999999),
    ("sum_range_skips", {"A1": "1", "A2": "x", "A4": "4", "B1": "=SUM(A1:A4)"}, "B1", 5),
    ("sum_mixed_args", {"A1": "1", "A2": "x", "A4": "4", "B1": "=SUM(A1:A2, 10, A4*2)"}, "B1", 19),
    ("sum_single_ref_string", {"A2": "x", "B1": "=SUM(A2)"}, "B1", "#VALUE!"),
    ("sum_single_cell_range_string", {"A2": "x", "B1": "=SUM(A2:A2)"}, "B1", 0),
    ("count_range_ignores", {"A1": "1", "A2": "x", "A3": "=1/0", "A4": "4", "B1": "=COUNT(A1:A4)"}, "B1", 2),
    ("count_expression_args", {"A2": "x", "A3": "=1/0", "B1": "=COUNT(A2, A3, 5)"}, "B1", 1),
    ("count_empty_ref_counts", {"B1": "=COUNT(Z1)"}, "B1", 1),
    ("count_empty_range", {"B1": "=COUNT(Z1:Z3)"}, "B1", 0),
    ("sum_error_in_range", {"A1": "1", "A3": "=1/0", "A4": "4", "B1": "=SUM(A1:A4)"}, "B1", "#DIV/0!"),
    ("min_range", {"A1": "1", "A2": "x", "A4": "4", "B1": "=MIN(A1:A4)"}, "B1", 1),
    ("max_range", {"A1": "1", "A2": "x", "A4": "4", "B1": "=MAX(A1:A4)"}, "B1", 4),
    ("min_no_numbers", {"A1": "x", "B1": "=MIN(A1:A3)"}, "B1", 0),
    ("max_empty_range", {"A1": "=MAX(B1:B3)"}, "A1", 0),
    ("min_negative_args", {"A1": "=MIN(-5, 3)"}, "A1", -5),
    ("range_reversed_corners", {"A1": "1", "B1": "2", "B2": "5", "C1": "=SUM(B2:A1)"}, "C1", 8),
    ("range_outside_function", {"A1": "1", "B1": "=A1:A3"}, "B1", "#VALUE!"),
    ("range_in_arithmetic", {"A1": "1", "B1": "=SUM(A1:A2)+A1:A2"}, "B1", "#VALUE!"),
    ("range_error_row_major", {"A1": "1", "C1": "x", "B1": "=C1+1", "A2": "=1/0", "D1": "=SUM(A1:B2)"},
     "D1", "#VALUE!"),
    ("binary_left_error_wins", {"A1": "=1/0", "C1": "x", "A2": "=C1+1", "B1": "=A2+A1"}, "B1", "#VALUE!"),
    ("binary_left_error_wins_2", {"A1": "=1/0", "C1": "x", "A2": "=C1+1", "B1": "=A1+A2"}, "B1", "#DIV/0!"),
    ("if_lazy_true", {"A1": "=IF(1, 5, 1/0)"}, "A1", 5),
    ("if_lazy_false", {"A1": "=IF(0, 1/0, 7)"}, "A1", 7),
    ("if_string_cond", {"A1": "x", "B1": "=IF(A1, 1, 2)"}, "B1", "#VALUE!"),
    ("if_error_cond", {"A1": "=IF(1/0, 1, 2)"}, "A1", "#DIV/0!"),
    ("if_empty_cond", {"A1": "=IF(Z1, 1, 2)"}, "A1", 2),
    ("if_range_branch", {"A1": "=IF(1, B1:B2, 3)"}, "A1", "#VALUE!"),
    ("if_wrong_arity", {"A1": "=IF(1, 2)"}, "A1", "#PARSE!"),
    ("empty_call", {"A1": "=SUM()"}, "A1", "#PARSE!"),
    ("unknown_function", {"A1": "=FOO(1)"}, "A1", "#NAME?"),
    ("bare_word", {"A1": "=FOO"}, "A1", "#NAME?"),
    ("ref_two_letters", {"A1": "=AA1"}, "A1", "#REF!"),
    ("ref_row_1000", {"A1": "=A1000"}, "A1", "#REF!"),
    ("ref_row_zero", {"A1": "=B0+1"}, "A1", "#REF!"),
    ("ref_leading_zero", {"A1": "=B01"}, "A1", "#REF!"),
    ("range_bad_corner", {"A1": "=SUM(B1:B1000)"}, "A1", "#REF!"),
    ("static_ref_in_untaken_branch", {"A1": "=IF(1, 2, AA1)"}, "A1", "#REF!"),
    ("static_name_in_untaken_branch", {"A1": "=IF(1, 2, FOO(3))"}, "A1", "#NAME?"),
    ("static_name_before_ref", {"A1": "=FOO(AA1)"}, "A1", "#NAME?"),
    ("parse_empty_formula", {"A1": "="}, "A1", "#PARSE!"),
    ("parse_trailing_operator", {"A1": "=1+"}, "A1", "#PARSE!"),
    ("parse_unclosed_paren", {"A1": "=(1"}, "A1", "#PARSE!"),
    ("parse_adjacent_numbers", {"A1": "=1 2"}, "A1", "#PARSE!"),
    ("parse_decimal", {"A1": "=1.5"}, "A1", "#PARSE!"),
    ("parse_trailing_comma", {"A1": "=SUM(1,)"}, "A1", "#PARSE!"),
    ("parse_double_equals", {"A1": "==1"}, "A1", "#PARSE!"),
    ("function_case_insensitive", {"A1": "1", "A2": "2", "B1": "=sum(a1:a2)"}, "B1", 3),
    ("cycle_self", {"A1": "=A1+1"}, "A1", "#CYCLE!"),
    ("cycle_pair_first", {"A1": "=B1", "B1": "=A1"}, "A1", "#CYCLE!"),
    ("cycle_pair_second", {"A1": "=B1", "B1": "=A1"}, "B1", "#CYCLE!"),
    ("cycle_downstream", {"A1": "=B1", "B1": "=A1", "C1": "=A1+1"}, "C1", "#CYCLE!"),
    ("cycle_static_if", {"A1": "=IF(1, 5, A1)"}, "A1", "#CYCLE!"),
    ("cycle_lazy_reader", {"A1": "=A1", "B1": "=IF(0, A1, 5)"}, "B1", 5),
    ("cycle_via_range", {"A1": "=SUM(A1:A3)"}, "A1", "#CYCLE!"),
    ("cycle_count_ignores", {"A1": "=A1", "B1": "=COUNT(A1, 3)"}, "B1", 1),
    ("cycle_long", {"A1": "=B1", "B1": "=C1", "C1": "=D1", "D1": "=A1", "E1": "=SUM(A1:A1)"}, "E1", "#CYCLE!"),
]
for _name, _cells, _cell, _want in SIMPLE:
    g.case(_name)(lambda m, ws, c=_cells, cell=_cell, w=_want: equal(make(m, c).get(cell), w))


@g.case("comparison_result_is_int")
def _(m, ws):
    v = make(m, {"A1": "=2>1"}).get("A1")
    equal((type(v).__name__, v), ("int", 1))


@g.case("set_empty_clears")
def _(m, ws):
    s = make(m, {"A1": "5"})
    s.set("A1", "")
    equal(s.get("A1"), None)


@g.case("name_case_insensitive")
def _(m, ws):
    s = make(m, {"b2": "7", "C1": "=b2+1"})
    equal((s.get("B2"), s.get("c1")), (7, 8))


g.case("invalid_set_row_zero")(lambda m, ws: raises(ValueError, m.Sheet().set, "A0", "1"))
g.case("invalid_set_two_letters")(lambda m, ws: raises(ValueError, m.Sheet().set, "AA1", "1"))
g.case("invalid_set_row_1000")(lambda m, ws: raises(ValueError, m.Sheet().set, "A1000", "1"))
g.case("invalid_get_leading_zero")(lambda m, ws: raises(ValueError, m.Sheet().get, "A01"))
g.case("set_non_str")(lambda m, ws: raises(TypeError, m.Sheet().set, "A1", 5))


@g.case("cycle_broken_by_update")
def _(m, ws):
    s = make(m, {"A1": "=B1", "B1": "=A1"})
    s.get("A1")
    s.set("B1", "3")
    equal(s.get("A1"), 3)


@g.case("recalc_after_update")
def _(m, ws):
    s = make(m, {"A1": "1", "B1": "=A1*2"})
    equal(s.get("B1"), 2)
    s.set("A1", "5")
    equal(s.get("B1"), 10)
    s.set("A1", "")
    equal(s.get("B1"), 0)


def _chain(m, reverse=False):
    s = m.Sheet()
    rows = range(999, 0, -1) if reverse else range(1, 1000)
    for r in rows:
        s.set(f"A{r}", "1" if r == 1 else f"=A{r - 1}+1")
    return s


g.case("deep_chain")(lambda m, ws: equal(_chain(m).get("A999"), 999))
g.case("deep_chain_reverse_set")(lambda m, ws: equal(_chain(m, reverse=True).get("A999"), 999))


@g.case("deep_chain_all_gets")
def _(m, ws):
    s = _chain(m)
    equal([s.get(f"A{r}") for r in range(1, 1000)], list(range(1, 1000)))


@g.case("deep_chain_update_bottom")
def _(m, ws):
    s = _chain(m)
    s.get("A999")
    s.set("A1", "1001")
    equal(s.get("A999"), 1999)


@g.case("full_sheet_sum")
def _(m, ws):
    s = m.Sheet()
    for col in "ABCDEFGHIJKLMNOPQRSTUVWXY":
        for r in range(1, 1000):
            s.set(f"{col}{r}", "1")
    for r in range(1, 999):
        s.set(f"Z{r}", "1")
    s.set("Z999", "=SUM(A1:Y999)+SUM(Z1:Z998)")
    equal(s.get("Z999"), 25 * 999 + 998)


if __name__ == "__main__":
    g.main()
