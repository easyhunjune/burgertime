# Duration strings — specification

Implement two functions in `duration.py`:

    parse_duration(text: str) -> int      # total number of seconds
    format_duration(seconds: int) -> str

## Units

| unit | seconds |
|------|---------|
| w    | 604800  |
| d    | 86400   |
| h    | 3600    |
| m    | 60      |
| s    | 1       |

## parse_duration

1. `text` must be a `str`; anything else raises `TypeError`.
2. Leading and trailing whitespace (spaces, tabs, newlines) is ignored.
3. After trimming, the text is an optional sign followed by one or more components.
   A component is `<number><unit>` with nothing between the number and the unit.
   Components may be separated by zero or more space characters (U+0020 only).
4. Unit letters are case-insensitive (`1H` is the same as `1h`).
5. Units must appear in strictly descending size order (w, d, h, m, s), and each unit at most once.
   `1h1d` and `1h1h` are invalid.
6. A number is one or more ASCII digits (`0`-`9`). Leading zeros are allowed (`007s` is 7).
7. Only the last component may have a fractional part, written as digits, a dot, digits — with at
   least one digit on each side of the dot (`1.5h` is fine, `.5h` and `1.h` are invalid).
   The total must come out to a whole number of seconds, otherwise the input is invalid
   (`1.5h` = 5400 is fine, `0.5s` and `1.01m` are invalid). Use exact decimal arithmetic, not floats.
8. The optional sign is a single `-` directly followed by the first component (no space after it).
   It negates the whole duration: `-1h30m` is -5400. A leading `+` is invalid.
9. The text `0` (after trimming, with no unit) is valid and equals 0. `-0` is also valid and equals 0.
   Any other number without a unit is invalid.
10. Anything else — empty input, unknown units, stray characters, separators other than spaces —
    raises `ValueError`.

## format_duration

1. `seconds` must be an `int`; `bool` and every other type raise `TypeError`.
2. `0` formats as `0s`.
3. Otherwise use the largest units first, omit zero components and join them without spaces:
   `90061` -> `1d1h1m1s`, `3600` -> `1h`, `604800` -> `1w`.
4. Negative values get a single leading `-`: `-90` -> `-1m30s`.
5. Output is always lowercase.

`parse_duration(format_duration(n)) == n` must hold for every integer `n`.
