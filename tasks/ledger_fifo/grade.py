import os
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("ledger")


@g.case("same_day_lots_fifo")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-03-01", 10, "12")
    led.buy("2024-03-01", 10, "10")
    equal(led.sell("2024-03-02", 5, "15"), D("15.00"))


@g.case("same_day_lots_order_in_lots")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-05", 1, "30")
    led.buy("2024-01-05", 1, "10")
    led.buy("2024-01-04", 1, "20")
    equal([(d, q, D(c)) for d, q, c in led.lots()],
          [("2024-01-04", 1, D("20")), ("2024-01-05", 1, D("30")), ("2024-01-05", 1, D("10"))])


@g.case("backfilled_buy_consumed_first")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-02-01", 5, "20")
    led.buy("2024-01-01", 5, "10")
    equal(led.sell("2024-03-01", 5, "15"), D("25.00"))


@g.case("partial_lot_cost_basis")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 10, "10")
    equal(led.sell("2024-01-02", 4, "12"), D("8.00"))
    equal(led.cost_basis(), D("60.00"))


@g.case("partial_lot_second_sale")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 10, "10")
    led.sell("2024-01-02", 4, "12")
    equal(led.sell("2024-01-03", 6, "12"), D("12.00"))


@g.case("partial_lot_keeps_unit_cost")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 10, "10")
    led.sell("2024-01-02", 4, "12")
    equal([(d, q, D(c)) for d, q, c in led.lots()], [("2024-01-01", 6, D("10"))])


@g.case("round_once_per_sale")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 3, "10", fee="1")
    led.buy("2024-01-02", 3, "10", fee="1")
    led.sell("2024-01-03", 2, "20")
    # consumes 1 unit from each lot at 31/3 each; 40 - 20.666... = 19.333... -> 19.33
    equal(led.sell("2024-01-04", 2, "20"), D("19.33"))


@g.case("round_half_up_sale")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 1, "10.015")
    equal(led.sell("2024-01-02", 1, "20"), D("9.99"))


@g.case("round_half_up_cost_basis")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 1, "10.005")
    equal(led.cost_basis(), D("10.01"))


@g.case("fees_in_cost_and_sale")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 4, "10", fee="2")
    equal(led.sell("2024-01-02", 4, "12", fee="1"), D("5.00"))


@g.case("realized_accumulates")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 10, "10")
    led.sell("2024-01-02", 3, "12")
    led.sell("2024-01-03", 2, "9")
    equal(led.realized, D("4.00"))


@g.case("oversell_raises")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 5, "10")
    raises(m.InsufficientQuantity, led.sell, "2024-01-02", 7, "12")


@g.case("oversell_leaves_state")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 5, "10")
    try:
        led.sell("2024-01-02", 7, "12")
    except m.InsufficientQuantity:
        pass
    equal(led.position(), 5)
    equal(led.realized, D("0"))
    equal([(d, q, D(c)) for d, q, c in led.lots()], [("2024-01-01", 5, D("10"))])


@g.case("oversell_multi_lot_leaves_state")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 3, "10")
    led.buy("2024-01-02", 3, "11")
    try:
        led.sell("2024-01-03", 7, "12")
    except m.InsufficientQuantity:
        pass
    equal(led.position(), 6)
    equal(led.cost_basis(), D("63.00"))


@g.case("sale_before_any_lot")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-03-01", 5, "10")
    raises(m.InsufficientQuantity, led.sell, "2024-02-01", 1, "12")


@g.case("sale_partially_eligible")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 2, "10")
    led.buy("2024-03-01", 5, "10")
    try:
        led.sell("2024-02-01", 3, "12")
        raise AssertionError("expected InsufficientQuantity")
    except m.InsufficientQuantity:
        pass
    equal(led.position(), 7)


@g.case("sale_with_later_lots_present")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 5, "10")
    led.buy("2024-03-01", 5, "20")
    equal(led.sell("2024-02-01", 5, "12"), D("10.00"))
    equal(led.position(), 5)


@g.case("float_price_rejected")
def _(m, ws):
    raises(TypeError, m.Ledger().buy, "2024-01-01", 1, 10.5)


@g.case("float_fee_rejected")
def _(m, ws):
    raises(TypeError, m.Ledger().buy, "2024-01-01", 1, "10", 0.5)


@g.case("float_sell_price_rejected")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 1, "10")
    raises(TypeError, led.sell, "2024-01-02", 1, 12.5)


@g.case("bool_qty_rejected")
def _(m, ws):
    raises(TypeError, m.Ledger().buy, "2024-01-01", True, "10")


@g.case("negative_price_rejected")
def _(m, ws):
    raises(ValueError, m.Ledger().buy, "2024-01-01", 1, "-1")


@g.case("int_and_decimal_prices")
def _(m, ws):
    led = m.Ledger()
    led.buy("2024-01-01", 2, 10)
    led.buy("2024-01-01", 2, D("10.50"))
    equal(led.sell("2024-01-02", 3, 11), D("2.50"))


if __name__ == "__main__":
    g.main()
