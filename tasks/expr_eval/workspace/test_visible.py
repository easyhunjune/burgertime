from calc import evaluate

assert evaluate("1 + 2 * 3") == 7
assert evaluate("(1 + 2) * 3") == 9
assert evaluate("x * 2", {"x": 21}) == 42
assert evaluate("max(1, 5, 3)") == 5
print("visible checks passed")
