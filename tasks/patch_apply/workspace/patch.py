"""Apply unified diffs. See README.md for the required behaviour."""
import re

_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(ValueError):
    pass


def _path(raw):
    path = raw.strip()
    if path == "/dev/null":
        return None
    return path.lstrip("ab/")


def _parse(patch):
    sections = []
    current = None
    lines = patch.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            current = {"old": _path(line[4:]), "new": _path(lines[i + 1][4:]), "hunks": []}
            sections.append(current)
            i += 2
            continue
        m = _HUNK.match(line)
        if m:
            if current is None:
                raise PatchError("hunk before file header")
            start = int(m.group(1))
            count = int(m.group(2) or 0)
            old, new = [], []
            i += 1
            while i < len(lines):
                body = lines[i]
                if not body or body[0] not in " -+\\":
                    break
                if body.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    break
                if body[0] in " -":
                    old.append(body[1:] + "\n")
                if body[0] in " +":
                    new.append(body[1:] + "\n")
                i += 1
            current["hunks"].append((start, count, old, new))
            continue
        i += 1
    return sections


def _apply(lines, hunks):
    for start, count, old, new in hunks:
        expected = start - 1 if count else start
        for offset in range(0, 21):
            pos = expected + offset
            if lines[pos:pos + len(old)] == old:
                break
        else:
            raise PatchError(f"hunk at line {start} does not apply")
        lines[pos:pos + len(old)] = new
    return lines


def apply_patch(files, patch):
    if not isinstance(files, dict) or not isinstance(patch, str):
        raise TypeError("apply_patch(files: dict, patch: str)")
    for section in _parse(patch):
        name = section["old"] or section["new"]
        lines = files.get(name, "").splitlines(keepends=True)
        lines = _apply(lines, section["hunks"])
        files[name] = "".join(lines)
    return files
