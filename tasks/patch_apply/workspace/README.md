# patch.py — apply unified diffs

`apply_patch(files, patch)` applies a unified diff to an in-memory set of files. Our release tooling
relies on exactly this behaviour:

## Interface

- `files` is a `dict` mapping a path (`str`) to its full text content (`str`, lines end with `"\n"`;
  the last line may have no newline). `patch` is a `str`. Other types raise `TypeError`.
- Returns a **new** dict with the patched files. Files the patch does not mention are copied unchanged.
  The input dict must never be modified, also not when an error is raised.
- Every problem raises `PatchError`, which is a subclass of `ValueError`.

## Patch format

- A file section starts with a line `--- <old path>` immediately followed by a line `+++ <new path>`.
  Each path ends at the first tab (anything after a tab, such as a timestamp, is ignored). A leading `a/`
  or `b/` is removed (only that exact prefix). The path `/dev/null` means "no file".
- The file being patched is the `+++` path. When the `+++` path is `/dev/null` the file is deleted, and the
  `---` path names it. When the `---` path is `/dev/null` the file is created: it must not exist yet and the
  hunks are applied to an empty file. A deleted file must be empty after its hunks are applied, and is then
  removed from the result.
- Lines outside hunks that are not file headers (`diff --git ...`, `index ...`, blank lines, ...) are ignored.
  A hunk header before the first file header is an error.
- A hunk header is `@@ -l,s +l,s @@`, optionally followed by more text. A missing `,s` means `s` is 1.
  When the old count `s` is 0, the old `l` is the line **after which** the new lines are inserted
  (`l` = 0 means at the beginning of the file).
- Hunk body lines start with `' '` (context), `'-'` (removed) or `'+'` (added). A completely empty line inside
  a hunk body is a context line with empty content.
- The body must contain exactly the old count of context + removed lines and the new count of context + added
  lines. The counts decide where the body ends (a body line may itself look like `--- x`). If the patch ends or
  an `@@` line appears before both counts are complete, or a body line (`' '`, `'-'`, `'+'`, other than a file
  header) follows right after both counts are complete, that is an error.
- `\ No newline at end of file` (any line starting with a backslash) says that the line just before it has
  no trailing newline: after a `'-'` line in the old file, after a `'+'` line in the new file, after a `' '`
  line in both. It may also appear in the middle of a hunk body.

## Applying hunks

- The hunks of a file are applied in order. The expected position of a hunk is the position given in its
  header, shifted by the number of lines added minus lines removed by the hunks already applied to that file.
- The hunk's old lines (context and removed lines, compared exactly, newlines included) must match the file at
  the expected position. If they do not, try the offsets +1, -1, +2, -2, ... up to 20 lines in each direction,
  in that order, and use the first offset that matches. A hunk may never start before the end of the previous
  hunk of the same file. If nothing matches, it is an error.
- The matched old lines are replaced by the hunk's new lines (context and added lines).
