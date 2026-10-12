"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


class InsufficientQuantity(ValueError):
    pass


def _to_decimal(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise TypeError(f"{name} must be str, int or Decimal")
    amount = value if isinstance(value, Decimal) else Decimal(value)
    if amount < 0:
        raise ValueError(f"{name} must be >= 0")
    return amount


def _check_qty(qty):
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise TypeError("qty must be int")
    if qty <= 0:
        raise ValueError("qty must be > 0")
    return qty


class Ledger:
    def __init__(self):
        self._lots = []  # [date, seq, qty, unit_cost]
        self._seq = 0
        self.realized = Decimal("0")

    def buy(self, date, qty, price, fee="0"):
        qty = _check_qty(qty)
        price = _to_decimal(price, "price")
        fee = _to_decimal(fee, "fee")
        self._lots.append([date, self._seq, qty, (qty * price + fee) / qty])
        self._seq += 1
        self._lots.sort(key=lambda lot: (lot[0], lot[1]))

    def sell(self, date, qty, price, fee="0"):
        qty = _check_qty(qty)
        price = _to_decimal(price, "price")
        fee = _to_decimal(fee, "fee")
        eligible = sum(lot[2] for lot in self._lots if lot[0] <= date)
        if eligible < qty:
            raise InsufficientQuantity(f"cannot sell {qty}: only {eligible} eligible")
        remaining, cost, kept = qty, Decimal(0), []
        for lot in self._lots:
            if remaining and lot[0] <= date:
                take = min(remaining, lot[2])
                cost += take * lot[3]
                remaining -= take
                if lot[2] > take:
                    kept.append([lot[0], lot[1], lot[2] - take, lot[3]])
            else:
                kept.append(lot)
        self._lots = kept
        pnl = (qty * price - fee - cost).quantize(CENT, rounding=ROUND_HALF_UP)
        self.realized += pnl
        return pnl

    def position(self):
        return sum(lot[2] for lot in self._lots)

    def cost_basis(self):
        total = sum((lot[2] * lot[3] for lot in self._lots), Decimal(0))
        return total.quantize(CENT, rounding=ROUND_HALF_UP)

    def lots(self):
        return [(lot[0], lot[2], lot[3]) for lot in self._lots]
