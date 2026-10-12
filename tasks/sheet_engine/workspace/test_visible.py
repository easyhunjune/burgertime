from sheet import Sheet

s = Sheet()
s.set("A1", "10")
s.set("A2", "32")
s.set("B1", "=A1*2+1")
s.set("B2", "=SUM(A1:A2)")
s.set("B3", "=A1/0")
assert s.get("B1") == 21
assert s.get("B2") == 42
assert s.get("B3") == "#DIV/0!"
assert s.get("C9") is None
print("visible checks passed")
