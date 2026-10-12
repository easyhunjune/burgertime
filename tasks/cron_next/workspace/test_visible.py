from datetime import datetime

from cronnext import next_fire

assert next_fire("30 9 * * *", datetime(2026, 3, 10, 8, 0)) == datetime(2026, 3, 10, 9, 30)
assert next_fire("30 9 * * *", datetime(2026, 3, 10, 9, 30)) == datetime(2026, 3, 11, 9, 30)
assert next_fire("*/15 * * * *", datetime(2026, 3, 10, 10, 7, 12)) == datetime(2026, 3, 10, 10, 15)
assert next_fire("0 12 1 JAN,jul *", datetime(2026, 2, 1)) == datetime(2026, 7, 1, 12, 0)
print("visible checks passed")
