"""FIFO lot ledger. See README.md for the required behaviour."""
from decimal import Decimal

CENT = Decimal("0.01")


class InsufficientQuantity(ValueError):
    pass


def _to_decimal(value, name):
    if isinstance(value, bool):
        raise TypeError(f"{name} must not be bool")
    if isinstance(value, Decimal):
        amount = value
    else:
        amount = Decimal(str(value))
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
        # each lot: {"date", "seq", "qty", "cost"} where cost is the lot's total cost
        self._lots = []
        self._seq = 0
        self.realized = Decimal("0")

    def buy(self, date, qty, price, fee="0"):
        qty = _check_qty(qty)
        price = _to_decimal(price, "price")
        fee = _to_decimal(fee, "fee")
        self._lots.append({"date": date, "seq": self._seq, "qty": qty, "cost": qty * price + fee})
        self._seq += 1
        self._lots.sort(key=lambda lot: (lot["date"], lot["cost"] / lot["qty"]))

    def sell(self, date, qty, price, fee="0"):
        qty = _check_qty(qty)
        price = _to_decimal(price, "price")
        fee = _to_decimal(fee, "fee")
        remaining = qty
        consumed_cost = Decimal("0")
        for lot in self._lots:
            if remaining == 0:
                break
            take = min(remaining, lot["qty"])
            unit_cost = lot["cost"] / lot["qty"]
            consumed_cost += (take * unit_cost).quantize(CENT)
            lot["qty"] -= take
            remaining -= take
        if remaining:
            raise InsufficientQuantity(f"cannot sell {qty}: only {qty - remaining} available")
        self._lots = [lot for lot in self._lots if lot["qty"] > 0]
        pnl = (qty * price - fee - consumed_cost).quantize(CENT)
        self.realized += pnl
        return pnl

    def position(self):
        return sum(lot["qty"] for lot in self._lots)

    def cost_basis(self):
        return sum((lot["cost"] for lot in self._lots), Decimal("0")).quantize(CENT)

    def lots(self):
        return [(lot["date"], lot["qty"], lot["cost"] / lot["qty"]) for lot in self._lots]
