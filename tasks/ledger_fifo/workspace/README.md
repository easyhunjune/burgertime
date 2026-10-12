# ledger.py — FIFO lot ledger

`Ledger` tracks lots of a single instrument. The rest of our system relies on this behaviour:

1. `buy(date, qty, price, fee="0")` records a lot. `sell(date, qty, price, fee="0")` closes
   quantity and returns the realized P&L of that sale.
2. `date` is an ISO string `YYYY-MM-DD`. Buys may be recorded out of chronological order
   (back-filled trades).
3. `qty` must be an `int` greater than 0 (`bool` is not accepted): wrong type raises `TypeError`,
   zero or negative raises `ValueError`.
4. `price` and `fee` may be `str`, `int` or `decimal.Decimal`. `float` and `bool` raise `TypeError`.
   Negative values raise `ValueError`.
5. A lot's unit cost is `(qty * price + fee) / qty`. Never round it.
6. Sales consume lots first-in-first-out: the earliest `date` first, and lots with the same `date`
   in the order they were recorded.
7. A sale can only consume lots whose `date` is on or before the sale's `date`.
8. Realized P&L of a sale = `qty * price - fee - (cost of the consumed quantity)`, where the
   consumed cost uses each lot's unit cost. Round **once** per sale, to cents, half-up
   (`ROUND_HALF_UP`). Intermediate values are never rounded.
9. When a lot is partially consumed, its remaining quantity keeps the same unit cost.
10. If a sale needs more quantity than the eligible lots hold, raise `InsufficientQuantity` and leave
    the ledger exactly as it was.
11. `realized` is the sum of all per-sale realized P&L values.
12. `position()` is the total remaining quantity. `cost_basis()` is the total remaining cost
    (sum of remaining qty × unit cost), rounded to cents half-up. `lots()` returns
    `(date, qty, unit_cost)` tuples in FIFO order, with the unrounded unit cost as a `Decimal`.
