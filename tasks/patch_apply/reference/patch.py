"""Reference solution (never shown to the model; used by `run_bench.py selftest`)."""
import re

MAX_OFFSET = 20
_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    pass


def _path(raw):
    path = raw.split("\t", 1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _split_lines(text):
    parts = text.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _is_header(lines, i):
    return lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")


def _parse(patch):
    lines = patch.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    sections, current, i = [], None, 0
    while i < len(lines):
        if _is_header(lines, i):
            current = {"old": _path(lines[i][4:]), "new": _path(lines[i + 1][4:]), "hunks": []}
            sections.append(current)
            i += 2
            continue
        if not lines[i].startswith("@@"):
            i += 1
            continue
        m = _HUNK.match(lines[i])
        if not m or current is None:
            raise PatchError(f"bad or misplaced hunk header: {lines[i]!r}")
        old_start = int(m.group(1))
        old_left = 1 if m.group(2) is None else int(m.group(2))
        new_left = 1 if m.group(4) is None else int(m.group(4))
        old_count = old_left
        old, new, last = [], [], None
        i += 1

        def marker():
            if last is None:
                raise PatchError("newline marker without a preceding line")
            if last in (" ", "-"):
                old[-1] = old[-1][:-1]
            if last in (" ", "+"):
                new[-1] = new[-1][:-1]

        while old_left or new_left:
            if i >= len(lines) or lines[i].startswith("@@"):
                raise PatchError("hunk is shorter than its header says")
            line = lines[i]
            kind, body = (line[0], line[1:]) if line else (" ", "")
            if kind == "\\":
                marker()
            elif kind == " " and old_left and new_left:
                old.append(body + "\n")
                new.append(body + "\n")
                old_left -= 1
                new_left -= 1
            elif kind == "-" and old_left:
                old.append(body + "\n")
                old_left -= 1
            elif kind == "+" and new_left:
                new.append(body + "\n")
                new_left -= 1
            else:
                raise PatchError(f"unexpected hunk line {line!r}")
            if kind != "\\":
                last = kind
            i += 1
        if i < len(lines) and lines[i].startswith("\\"):
            marker()
            i += 1
        if i < len(lines) and lines[i][:1] in (" ", "-", "+") and not _is_header(lines, i):
            raise PatchError("hunk is longer than its header says")
        current["hunks"].append((old_start, old_count, old, new))
    return sections


def _apply_hunks(lines, hunks):
    out, delta, floor = list(lines), 0, 0
    for old_start, old_count, old, new in hunks:
        expected = (old_start if old_count == 0 else old_start - 1) + delta
        offsets = [0] + [o for k in range(1, MAX_OFFSET + 1) for o in (k, -k)]
        for off in offsets:
            pos = expected + off
            if floor <= pos and pos + len(old) <= len(out) and out[pos:pos + len(old)] == old:
                break
        else:
            raise PatchError(f"hunk at line {old_start} does not apply")
        out[pos:pos + len(old)] = new
        delta += len(new) - len(old)
        floor = pos + len(new)
    return out


def apply_patch(files, patch):
    if not isinstance(files, dict) or not isinstance(patch, str):
        raise TypeError("apply_patch(files: dict, patch: str)")
    result = dict(files)
    for section in _parse(patch):
        old, new = section["old"], section["new"]
        if old is None and new is None:
            raise PatchError("both paths are /dev/null")
        target = new if new is not None else old
        if old is None:
            if target in result:
                raise PatchError(f"{target} already exists")
            lines = []
        else:
            if target not in result:
                raise PatchError(f"{target} does not exist")
            lines = _split_lines(result[target])
        lines = _apply_hunks(lines, section["hunks"])
        if new is None:
            if lines:
                raise PatchError(f"{target} is not empty after deletion")
            del result[target]
        else:
            result[target] = "".join(lines)
    return result
