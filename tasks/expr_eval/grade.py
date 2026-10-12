import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("calc")

VALUES = [
    ("precedence_mul", "1 + 2 * 3", None, 7),
    ("left_assoc_sub", "10 - 2 - 3", None, 5),
    ("left_assoc_div", "100 / 10 / 5", None, 2),
    ("power_right_assoc", "2^3^2", None, 512),
    ("power_parenthesized", "(2^3)^2", None, 64),
    ("power_over_mul", "2*3^2", None, 18),
    ("neg_power", "-2^2", None, -4),
    ("paren_neg_power", "(-2)^2", None, 4),
    ("zero_pow_zero", "0^0", None, 1),
    ("big_power", "2^100", None, 2**100),
    ("big_literal", "123456789012345678901234567890 * 10", None, 1234567890123456789012345678900),
    ("trunc_div_pos", "7/2", None, 3),
    ("trunc_div_neg_left", "-7/2", None, -3),
    ("trunc_div_neg_right", "7/-2", None, -3),
    ("trunc_div_both_neg", "-7/-2", None, 3),
    ("rem_neg_left", "-7%2", None, -1),
    ("rem_neg_right", "7%-2", None, 1),
    ("rem_both_neg", "-7%-2", None, -1),
    ("unary_after_plus", "1+-2", None, -1),
    ("unary_after_minus", "1--2", None, 3),
    ("double_unary", "--3", None, 3),
    ("unary_after_mul", "2*-3", None, -6),
    ("neg_group", "-(2+3)", None, -5),
    ("whitespace_tabs", " 1 +\t2 ", None, 3),
    ("variables", "x*2+y", {"x": 5, "y": -1}, 9),
    ("abs_call", "abs(-5)", None, 5),
    ("min_call", "min(3, 1, 2)", None, 1),
    ("max_single_arg", "max(-1)", None, -1),
    ("nested_calls", "max(2, min(5, 3))", None, 3),
    ("call_ignores_variable", "abs(-3)", {"abs": 10}, 3),
    ("function_name_as_variable", "abs + 1", {"abs": 3}, 4),
]
for _name, _expr, _vars, _want in VALUES:
    g.case(_name)(lambda m, ws, e=_expr, v=_vars, w=_want: equal(m.evaluate(e, v), w))

ERRORS = [
    ("div_by_zero", "1/0", None, ZeroDivisionError),
    ("mod_by_zero", "1%0", None, ZeroDivisionError),
    ("negative_exponent", "2^-1", None, ValueError),
    ("missing_variable", "z + 1", {}, NameError),
    ("bool_variable", "x", {"x": True}, TypeError),
    ("float_variable", "x", {"x": 1.5}, TypeError),
    ("abs_arity", "abs(1, 2)", None, TypeError),
    ("unknown_function", "foo(1)", None, NameError),
    ("syntax_empty", "", None, SyntaxError),
    ("syntax_unclosed", "(1+2", None, SyntaxError),
    ("syntax_unopened", "1+2)", None, SyntaxError),
    ("syntax_trailing_op", "1+", None, SyntaxError),
    ("syntax_leading_op", "*2", None, SyntaxError),
    ("syntax_implicit_mul_paren", "2(3)", None, SyntaxError),
    ("syntax_implicit_mul_name", "2x", {"x": 1}, SyntaxError),
    ("syntax_implicit_mul_groups", "(1)(2)", None, SyntaxError),
    ("syntax_unary_plus", "+1", None, SyntaxError),
    ("syntax_float_literal", "1.5", None, SyntaxError),
    ("syntax_exponent_literal", "1e3", None, SyntaxError),
    ("syntax_adjacent_numbers", "1 2", None, SyntaxError),
    ("syntax_empty_args", "max()", None, SyntaxError),
    ("syntax_trailing_comma", "min(1,)", None, SyntaxError),
    ("syntax_newline", "1\n+2", None, SyntaxError),
    ("syntax_invalid_char", "3 $ 4", None, SyntaxError),
    ("syntax_non_ascii_digit", "١+1", None, SyntaxError),
]
for _name, _expr, _vars, _exc in ERRORS:
    g.case(_name)(lambda m, ws, e=_expr, v=_vars, x=_exc: raises(x, m.evaluate, e, v))

g.case("type_not_str")(lambda m, ws: raises(TypeError, m.evaluate, 5))


@g.case("no_eval_or_ast")
def _no_eval(m, ws):
    with open(os.path.join(ws, "calc.py"), encoding="utf-8", errors="replace") as fh:
        source = fh.read()
    # re.compile( 같은 속성 호출은 허용하고, 맨 이름으로 부르는 eval/exec/compile만 잡는다.
    banned = re.search(r"(?<![\w.])(eval|exec|compile)\s*\(|^\s*(import|from)\s+ast\b", source, re.M)
    if banned:
        raise AssertionError(f"forbidden construct: {banned.group(0).strip()}")


if __name__ == "__main__":
    g.main()
