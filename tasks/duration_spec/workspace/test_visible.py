from duration import format_duration, parse_duration

assert parse_duration("1h30m") == 5400
assert parse_duration("2d 4h") == 187200
assert format_duration(90061) == "1d1h1m1s"
assert format_duration(-90) == "-1m30s"
print("visible checks passed")
