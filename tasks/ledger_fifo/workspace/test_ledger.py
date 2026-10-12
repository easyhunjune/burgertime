from decimal import Decimal

from ledger import Ledger


def test_same_day_lots_are_fifo():
    led = Ledger()
    led.buy("2024-03-01", 10, "12")
    led.buy("2024-03-01", 10, "10")
    pnl = led.sell("2024-03-02", 5, "15")
    # the 12.00 lot was recorded first, so it must be consumed first
    assert pnl == Decimal("15.00"), pnl


if __name__ == "__main__":
    test_same_day_lots_are_fifo()
    print("visible checks passed")
