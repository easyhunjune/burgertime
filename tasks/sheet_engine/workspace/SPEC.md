# Spreadsheet engine — specification

Implement class `Sheet` in `sheet.py`:

    sheet = Sheet()
    sheet.set("A1", "10")
    sheet.set("B1", "=A1*2")
    sheet.get("B1")   # -> 20

## Cells

- A cell name is one letter `A`-`Z` followed by a row number 1-999 written without leading zeros
  (`A1`, `Z999`). Letters are case-insensitive everywhere (`b2` is `B2`).
- `set(name, raw)`: `raw` must be a `str`, otherwise `TypeError`. An invalid name raises `ValueError`.
  `set(name, "")` makes the cell empty.
- `get(name)`: an invalid name raises `ValueError`. Returns the cell's current value: an `int`, a `str`,
  an error string (see Errors) or `None` for an empty cell. Values always reflect every `set` made so far.
- `raw` is interpreted as:
  - starting with `=`: a formula; the rest of the text is the expression;
  - matching `-?[0-9]+` exactly (no spaces): that integer;
  - anything else: that exact text as a string value (`" 5"`, `"1.5"`, `"abc"` are strings).

## Expressions

- Tokens: integers (ASCII digits), cell references (`A1`), ranges (`A1:B3`, the two corners in any order
  describe the same rectangle), function calls `NAME(arg, ...)`, parentheses, operators.
  Spaces may appear between tokens. Function names are case-insensitive.
- Operators, from lowest to highest precedence:
  1. comparisons `=`, `<>`, `<`, `>`, `<=`, `>=` — non-associative (`1<2<3` is a parse error)
  2. `+`, `-` — left-associative
  3. `*`, `/` — left-associative
  4. unary `-`
- Comparisons produce `1` (true) or `0` (false), as `int`.
- `/` is integer division that truncates toward zero (`-7/2` is `-3`).
- Integers have unlimited size (Python `int`).

## Values inside expressions

- A reference to an empty cell evaluates to `0`.
- A reference to a string cell evaluates to that string. Arithmetic (`+ - * /` and unary `-`) with a
  string operand gives `#VALUE!`.
- `=` and `<>` accept any two values; a number never equals a string.
- `<`, `>`, `<=`, `>=` compare two numbers numerically or two strings in Python string order;
  a number compared with a string gives `#VALUE!`.

## Functions

- `SUM`, `MIN`, `MAX`, `COUNT` take one or more arguments. Each argument is either a range or an expression.
  - Range argument: empty cells and string cells are skipped. For `SUM`/`MIN`/`MAX`, an error value in the
    range makes the result that error. `COUNT` counts the numbers and ignores strings and errors.
  - Expression argument (including a single reference like `A1`): a number is used. For `SUM`/`MIN`/`MAX`,
    a string gives `#VALUE!` and an error gives that error. `COUNT` ignores strings and errors.
  - `SUM`, `MIN` and `MAX` of no numbers are `0`.
- `IF(cond, a, b)` takes exactly three arguments. `cond` must be a number: nonzero chooses `a`, zero chooses
  `b`. Only the chosen branch is evaluated. A string `cond` gives `#VALUE!`; an error `cond` gives that error.
- A range anywhere other than directly as an argument of `SUM`/`MIN`/`MAX`/`COUNT` gives `#VALUE!`.
- A call with an empty argument list, or `IF` with other than three arguments, is a parse error.

## Errors

Errors are values: the strings `#PARSE!`, `#NAME?`, `#REF!`, `#VALUE!`, `#DIV/0!`, `#CYCLE!`.

- `#PARSE!` — the formula does not follow the grammar (`=`, `=1+`, `=(1`, `=1 2`, `=1.5`, `=SUM()`).
- `#NAME?` — a call to an unknown function, or a bare word that is not followed by `(` (`=FOO`).
- `#REF!` — letters followed by digits that do not form a valid cell name (`AA1`, `A0`, `A01`, `A1000`),
  used as a reference or as a range corner.
- `#DIV/0!` — division by zero.
- Errors propagate: an operation with an error operand gives that error. When both operands of a binary
  operator are errors, the left one wins. Function arguments are processed left to right and ranges row by
  row (top to bottom, left to right within a row); the first error met is the result.
  `#PARSE!`, `#NAME?` and `#REF!` found anywhere in a formula make the whole formula that error, checked
  in that order, before anything is evaluated.

## Cycles

- References are static: every reference and every cell of every range written in a formula is a
  dependency, even inside an `IF` branch that is not taken.
- A cell that depends on itself, directly or through other cells, is in a cycle; its value is `#CYCLE!`.
- A cell that is not in a cycle but reads a cycle cell gets `#CYCLE!` from that read, like any other
  error value (so `IF(0, A1, 5)` is `5` even if `A1` is in a cycle).

## Scale

A sheet may fill all 26 x 999 cells, and a chain of formulas may be 999 cells long (`A2` reads `A1`,
`A3` reads `A2`, ...). `get` must handle that, and 999 `get` calls in a row on such a sheet must finish
within a couple of seconds.
