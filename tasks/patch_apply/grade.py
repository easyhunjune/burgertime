import copy
import difflib
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _grading import Grader, equal, raises  # noqa: E402

g = Grader("patch")


def lines(*items):
    return "".join(f"{x}\n" for x in items)


def numbered(n, prefix="line"):
    return [f"{prefix}{i}" for i in range(1, n + 1)]


def check(m, files, patch, want):
    equal(m.apply_patch(files, patch), want)


def check_error(m, files, patch):
    raises(m.PatchError, m.apply_patch, files, patch)


# ------------------------------------------------------------ basic hunks

@g.case("basic_single_hunk")
def _(m, ws):
    check(m, {"main.py": lines(*numbered(5))},
          "--- a/main.py\n+++ b/main.py\n@@ -2,3 +2,3 @@\n line2\n-line3\n+LINE3\n line4\n",
          {"main.py": lines("line1", "line2", "LINE3", "line4", "line5")})


@g.case("omitted_counts")
def _(m, ws):
    check(m, {"main.py": lines("x", "y", "z")},
          "--- a/main.py\n+++ b/main.py\n@@ -3 +3 @@\n-z\n+Z\n",
          {"main.py": lines("x", "y", "Z")})


@g.case("insert_at_beginning")
def _(m, ws):
    check(m, {"main.py": lines("x", "y")},
          "--- a/main.py\n+++ b/main.py\n@@ -0,0 +1,2 @@\n+first\n+second\n",
          {"main.py": lines("first", "second", "x", "y")})


@g.case("insert_after_line")
def _(m, ws):
    check(m, {"main.py": lines("l1", "l2", "l3", "l4")},
          "--- a/main.py\n+++ b/main.py\n@@ -3,0 +4,2 @@\n+n1\n+n2\n",
          {"main.py": lines("l1", "l2", "l3", "n1", "n2", "l4")})


@g.case("delete_lines")
def _(m, ws):
    check(m, {"main.py": lines("a", "b", "c", "d")},
          "--- a/main.py\n+++ b/main.py\n@@ -2,2 +1,0 @@\n-b\n-c\n",
          {"main.py": lines("a", "d")})


# ------------------------------------------------------------ multiple hunks and offsets

@g.case("two_hunks_growth")
def _(m, ws):
    src = numbered(60)
    added = [f"new{i}" for i in range(25)]
    patch = ("--- a/main.py\n+++ b/main.py\n"
             "@@ -2,2 +2,27 @@\n line2\n" + "".join(f"+{x}\n" for x in added) + " line3\n"
             "@@ -40,3 +65,3 @@\n line40\n-line41\n+LINE41\n line42\n")
    want = src[:2] + added + src[2:40] + ["LINE41"] + src[41:]
    check(m, {"main.py": lines(*src)}, patch, {"main.py": lines(*want)})


@g.case("two_hunks_shrink")
def _(m, ws):
    src = numbered(30)
    patch = ("--- a/main.py\n+++ b/main.py\n"
             "@@ -4,5 +4,2 @@\n line4\n-line5\n-line6\n-line7\n line8\n"
             "@@ -20,3 +17,3 @@\n line20\n-line21\n+LINE21\n line22\n")
    want = src[:4] + src[7:20] + ["LINE21"] + src[21:]
    check(m, {"main.py": lines(*src)}, patch, {"main.py": lines(*want)})


HUNK_AT_10 = "--- a/main.py\n+++ b/main.py\n@@ -10,3 +10,3 @@\n line10\n-line11\n+LINE11\n line12\n"


def _offset_case(m, shift):
    src = numbered(30)
    if shift > 0:
        src = [f"extra{i}" for i in range(shift)] + src
    else:
        src = src[-shift:]
    want = [("LINE11" if x == "line11" else x) for x in src]
    check(m, {"main.py": lines(*src)}, HUNK_AT_10, {"main.py": lines(*want)})


def _offset_back_20(m):
    # 헤더는 30번째 줄이라고 하지만 실제 내용은 10번째 줄에 있다 (오프셋 -20)
    src = numbered(60)
    patch = "--- a/main.py\n+++ b/main.py\n@@ -30,3 +30,3 @@\n line10\n-line11\n+LINE11\n line12\n"
    want = [("LINE11" if x == "line11" else x) for x in src]
    check(m, {"main.py": lines(*src)}, patch, {"main.py": lines(*want)})


g.case("offset_forward")(lambda m, ws: _offset_case(m, 2))
g.case("offset_backward")(lambda m, ws: _offset_case(m, -2))
g.case("offset_forward_20")(lambda m, ws: _offset_case(m, 20))
g.case("offset_backward_20")(lambda m, ws: _offset_back_20(m))


@g.case("offset_21_fails")
def _(m, ws):
    src = [f"extra{i}" for i in range(21)] + numbered(30)
    check_error(m, {"main.py": lines(*src)}, HUNK_AT_10)


@g.case("offset_prefers_plus")
def _(m, ws):
    check(m, {"main.py": lines("a", "dup", "b", "dup", "c")},
          "--- a/main.py\n+++ b/main.py\n@@ -3,1 +3,1 @@\n-dup\n+DUP\n",
          {"main.py": lines("a", "dup", "b", "DUP", "c")})


@g.case("hunk_cannot_overlap_previous")
def _(m, ws):
    # 첫 hunk가 x를 y,x로 바꾼다. 두 번째 hunk의 x는 오프셋 -2에서만 맞는데, 그 자리는 첫 hunk가 만든 줄이라 쓸 수 없다.
    check_error(m, {"main.py": lines("x", "q", "r")},
                "--- a/main.py\n+++ b/main.py\n@@ -1 +1,2 @@\n-x\n+y\n+x\n@@ -3 +4 @@\n-x\n+Z\n")


# ------------------------------------------------------------ body parsing

@g.case("empty_line_is_context")
def _(m, ws):
    check(m, {"main.py": "def f():\n\n    return 1\n"},
          "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,3 @@\n def f():\n\n-    return 1\n+    return 2\n",
          {"main.py": "def f():\n\n    return 2\n"})


@g.case("body_line_like_header")
def _(m, ws):
    check(m, {"main.py": lines("-- old", "keep")},
          "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n--- old\n+++ new\n keep\n",
          {"main.py": lines("++ new", "keep")})


@g.case("count_too_few_lines")
def _(m, ws):
    check_error(m, {"main.py": lines("a", "b", "c")},
                "--- a/main.py\n+++ b/main.py\n@@ -1,3 +1,3 @@\n a\n b\n")


@g.case("count_too_many_lines")
def _(m, ws):
    check_error(m, {"main.py": lines("a")},
                "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,2 @@\n a\n+b\n+c\n")


@g.case("context_mismatch")
def _(m, ws):
    check_error(m, {"main.py": lines("a", "b", "c")},
                "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n a\n-x\n+y\n")


# ------------------------------------------------------------ newline at end of file

@g.case("no_newline_in_old")
def _(m, ws):
    check(m, {"main.py": "a\nb"},
          "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n a\n-b\n\\ No newline at end of file\n+b\n",
          {"main.py": "a\nb\n"})


@g.case("no_newline_in_new")
def _(m, ws):
    check(m, {"main.py": "a\nb\n"},
          "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n\\ No newline at end of file\n",
          {"main.py": "a\nc"})


@g.case("no_newline_on_context")
def _(m, ws):
    check(m, {"main.py": "x\ny"},
          "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n-x\n+X\n y\n\\ No newline at end of file\n",
          {"main.py": "X\ny"})


@g.case("no_newline_both_sides")
def _(m, ws):
    check(m, {"main.py": "a\nold"},
          "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,3 @@\n a\n-old\n\\ No newline at end of file\n"
          "+new\n+tail\n\\ No newline at end of file\n",
          {"main.py": "a\nnew\ntail"})


# ------------------------------------------------------------ files and paths

@g.case("delete_file")
def _(m, ws):
    check(m, {"old.txt": lines("one", "two"), "keep.txt": lines("k")},
          "--- a/old.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-one\n-two\n",
          {"keep.txt": lines("k")})


@g.case("delete_file_not_empty")
def _(m, ws):
    check_error(m, {"old.txt": lines("one", "two", "three")},
                "--- a/old.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-one\n-two\n")


@g.case("create_file")
def _(m, ws):
    check(m, {"keep.txt": lines("k")},
          "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n",
          {"keep.txt": lines("k"), "new.txt": lines("hello", "world")})


@g.case("create_existing_file")
def _(m, ws):
    check_error(m, {"new.txt": lines("x")},
                "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,1 @@\n+hello\n")


@g.case("prefix_stripped_exactly")
def _(m, ws):
    check(m, {"bin/build.sh": lines("echo 1")},
          "--- a/bin/build.sh\n+++ b/bin/build.sh\n@@ -1,1 +1,1 @@\n-echo 1\n+echo 2\n",
          {"bin/build.sh": lines("echo 2")})


@g.case("target_is_plus_path")
def _(m, ws):
    check(m, {"notes.txt": lines("a", "b")},
          "--- notes.txt.orig\n+++ notes.txt\n@@ -1,2 +1,2 @@\n a\n-b\n+B\n",
          {"notes.txt": lines("a", "B")})


@g.case("timestamp_after_tab")
def _(m, ws):
    check(m, {"main.py": lines("v1")},
          "--- main.py\t2026-10-01 10:00:00.000000000 +0900\n"
          "+++ main.py\t2026-10-02 11:30:00.000000000 +0900\n@@ -1,1 +1,1 @@\n-v1\n+v2\n",
          {"main.py": lines("v2")})


@g.case("git_headers_and_multiple_files")
def _(m, ws):
    patch = ("diff --git a/main.py b/main.py\nindex 83db48f..bf269f4 100644\n"
             "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-x = 1\n+x = 2\n"
             "diff --git a/src/util.py b/src/util.py\nindex 1111111..2222222 100644\n"
             "--- a/src/util.py\n+++ b/src/util.py\n@@ -1,2 +1,3 @@\n def u():\n+    pass\n     return 0\n")
    check(m, {"main.py": lines("x = 1"), "src/util.py": lines("def u():", "    return 0"), "other.md": "o\n"},
          patch,
          {"main.py": lines("x = 2"), "src/util.py": lines("def u():", "    pass", "    return 0"),
           "other.md": "o\n"})


@g.case("missing_file")
def _(m, ws):
    check_error(m, {}, "--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")


@g.case("hunk_before_header")
def _(m, ws):
    check_error(m, {"main.py": lines("a")}, "@@ -1,1 +1,1 @@\n-a\n+b\n")


@g.case("input_not_mutated")
def _(m, ws):
    files = {"main.py": lines("a", "b"), "keep.txt": lines("k")}
    before = copy.deepcopy(files)
    result = m.apply_patch(files, "--- a/main.py\n+++ b/main.py\n@@ -2,1 +2,1 @@\n-b\n+B\n")
    equal(files, before)
    equal(result is files, False)


@g.case("input_not_mutated_on_error")
def _(m, ws):
    files = {"main.py": lines("a"), "util.py": lines("u")}
    before = copy.deepcopy(files)
    patch = ("--- a/main.py\n+++ b/main.py\n@@ -1,1 +1,1 @@\n-a\n+A\n"
             "--- a/util.py\n+++ b/util.py\n@@ -1,1 +1,1 @@\n-nope\n+x\n")
    try:
        m.apply_patch(files, patch)
    except m.PatchError:
        pass
    equal(files, before)


g.case("type_patch_not_str")(lambda m, ws: raises(TypeError, m.apply_patch, {}, b"--- a\n"))
g.case("type_files_not_dict")(lambda m, ws: raises(TypeError, m.apply_patch, [("a", "b")], ""))


@g.case("patch_error_is_value_error")
def _(m, ws):
    equal(issubclass(m.PatchError, ValueError), True)
    raises(ValueError, m.apply_patch, {}, "--- a/x\n+++ b/x\n@@ -1,1 +1,1 @@\n-a\n+b\n")


# ------------------------------------------------------------ round trips with difflib

WORDS = ["alpha", "beta", "gamma", "delta", "", "  indent", "end"]


def _mutate(rng, src):
    out = list(src)
    for _ in range(rng.randint(1, 6)):
        op = rng.choice("idr")
        if op == "i" or not out:
            out.insert(rng.randint(0, len(out)), rng.choice(WORDS) + str(rng.randint(0, 3)))
        elif op == "d":
            del out[rng.randrange(len(out))]
        else:
            out[rng.randrange(len(out))] = rng.choice(WORDS)
    return out


def _roundtrip(m, context, seed):
    rng = random.Random(seed)
    for _ in range(25):
        a = [rng.choice(WORDS) for _ in range(rng.randint(0, 40))]
        b = _mutate(rng, a)
        a_text, b_text = lines(*a), lines(*b)
        patch = "".join(difflib.unified_diff(a_text.splitlines(True), b_text.splitlines(True),
                                             "a/f.txt", "b/f.txt", n=context))
        equal(m.apply_patch({"f.txt": a_text}, patch), {"f.txt": b_text})


g.case("roundtrip_context_3")(lambda m, ws: _roundtrip(m, 3, 1))
g.case("roundtrip_context_1")(lambda m, ws: _roundtrip(m, 1, 2))
g.case("roundtrip_context_0")(lambda m, ws: _roundtrip(m, 0, 3))


if __name__ == "__main__":
    g.main()
