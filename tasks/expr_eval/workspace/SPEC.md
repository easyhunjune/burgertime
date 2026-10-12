# Integer expression evaluator — specification

Implement `evaluate(expr, variables=None)` in `calc.py`. It returns a Python `int`.

## Lexical rules

- Spaces and tabs may appear between tokens and are ignored. Any other whitespace character is invalid.
- Integer literals: one or more ASCII digits (`0`-`9`). There are no fractional or exponent
  literals (`1.5` and `1e3` are invalid).
- Names: an ASCII letter or `_`, followed by ASCII letters, ASCII digits or `_`.
- Operators and punctuation: `+ - * / % ^ ( ) ,`

## Operators (highest precedence first)

1. `^` power, right-associative: `2^3^2` is `2^(3^2)` = 512.
2. Unary `-`, so `-2^2` is `-(2^2)` = -4. The right operand of `^` may itself start with a
   unary minus (`2^-1` parses, then fails the exponent rule below). There is no unary `+`.
3. `*`, `/`, `%`, left-associative.
4. Binary `+` and `-`, left-associative.

A unary minus may follow a binary operator or another unary minus: `1+-2` = -1, `1--2` = 3, `--3` = 3.

## Semantics

- `/` is integer division that truncates toward zero: `7/2` = 3, `-7/2` = -3, `7/-2` = -3.
- `%` is the matching remainder, so `a == (a/b)*b + a%b` always holds: `-7%2` = -1, `7%-2` = 1.
- `/` or `%` by zero raises `ZeroDivisionError`.
- `a^b` with `b < 0` raises `ValueError`. `0^0` = 1.
- A name is looked up in `variables` (a dict; `None` means no variables). A missing name raises
  `NameError`. A variable whose value is not an `int`, or is a `bool`, raises `TypeError`.
- Functions: `abs(x)` takes exactly 1 argument; `min(...)` and `max(...)` take 1 or more arguments.
  A call with the wrong number of arguments raises `TypeError`. A call to any other name raises
  `NameError`. A name directly followed by `(` is always a function call, even if `variables`
  has an entry with that name; a name not followed by `(` is always a variable.
- Argument lists cannot be empty: `max()` is a syntax error.
- Integers have unlimited size (Python `int`).

## Errors

- `expr` that is not a `str` raises `TypeError`.
- Anything that does not follow the rules above raises `SyntaxError`. That includes: empty input,
  unbalanced parentheses, a missing operand (`1+`, `*2`), implicit multiplication (`2(3)`, `2x`,
  `(1)(2)`), unary `+`, empty argument lists and trailing commas (`max()`, `min(1,)`), and invalid
  characters.
- Do not use `eval`, `exec`, `compile` or the `ast` module.
