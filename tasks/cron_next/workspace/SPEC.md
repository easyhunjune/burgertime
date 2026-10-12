# cron next-fire calculator — specification

Implement `next_fire(expr, after)` in `cronnext.py`.

- `expr` is a cron expression (`str`); anything else raises `TypeError`.
- `after` is a naive `datetime.datetime`. A `datetime.date` that is not a `datetime`, or any other type,
  raises `TypeError`. A timezone-aware `datetime` raises `ValueError`.
- Return the earliest naive `datetime` that is **strictly later** than `after` and matches `expr`.
  The result always has `second == 0` and `microsecond == 0`.
- If nothing matches within 1500 days after `after`, raise `ValueError`.
- Any invalid expression raises `ValueError`.

## Expression

Exactly five fields separated by whitespace (any amount of spaces or tabs; leading and trailing
whitespace is ignored):

| field        | allowed values                     | names                          |
|--------------|------------------------------------|--------------------------------|
| minute       | 0-59                               |                                |
| hour         | 0-23                               |                                |
| day of month | 1-31                               |                                |
| month        | 1-12                               | `JAN`-`DEC`                    |
| day of week  | 0-7 (0 and 7 both mean Sunday)     | `SUN` `MON` `TUE` `WED` `THU` `FRI` `SAT` |

Names are case-insensitive and may be used anywhere a number may be used in their field
(including in ranges, e.g. `MON-FRI`).

A field is a comma-separated list of one or more items. Every item is one of:

- `*` — every value. For day of week, `*` covers 0-6.
- `n` — a single value.
- `a-b` — every value from `a` to `b` inclusive. `a` must not be greater than `b` (no wrap-around).
  In day of week, `b` may be 7 (`5-7` is Friday, Saturday, Sunday).
- `*/s`, `a-b/s` — every `s`-th value of `*` or of `a-b`, starting with the first one. `s` is at least 1.
- `a/s` — shorthand for `a-M/s` where `M` is the largest value `*` covers in that field
  (59, 23, 31, 12 and 6).

Numbers are plain ASCII digits (no signs). Out-of-range values, empty items, unknown names and any
other syntax raise `ValueError`.

### Extensions

Day of month may also contain these items:

- `L` — the last day of the month.
- `LW` — the last weekday (Monday-Friday) of the month.
- `nW` (`n` is 1-31) — the weekday nearest to day `n` of the month. If day `n` is a Saturday, use the
  Friday before it, unless that Friday is in the previous month, in which case use the Monday after it.
  If day `n` is a Sunday, use the Monday after it, unless that Monday is in the next month, in which case
  use the Friday before it. If the month has fewer than `n` days, `nW` matches nothing in that month.

Day of week may also contain these items (`n` is a number 0-7, no names):

- `nL` — the last day-`n` of the month (`5L` = the last Friday).
- `n#k` (`k` is 1-5) — the `k`-th day-`n` of the month (`3#2` = the second Wednesday). If the month has
  no `k`-th such day, it matches nothing in that month.

These items may appear in comma lists together with ordinary items (`1,15,L`). They are only valid in
the field listed here; anywhere else they raise `ValueError`.

### Matching days

A time matches when its minute, hour and month are in their fields and its day matches.

The day rule follows classic cron: a day-of-month or day-of-week field is **unrestricted** if its text
begins with `*` (this includes `*/2`). If either of the two fields is unrestricted, the day must match
both fields. If both are restricted, the day matches when it matches **either** field.

### Macros

The whole expression may instead be one of these (exactly as written):

| macro                      | same as       |
|----------------------------|---------------|
| `@yearly`, `@annually`     | `0 0 1 1 *`   |
| `@monthly`                 | `0 0 1 * *`   |
| `@weekly`                  | `0 0 * * 0`   |
| `@daily`, `@midnight`      | `0 0 * * *`   |
| `@hourly`                  | `0 * * * *`   |
