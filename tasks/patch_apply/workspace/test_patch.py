from patch import apply_patch

PATCH = """\
--- a/config.ini
+++ b/config.ini
@@ -2 +2 @@
-port = 8080
+port = 9090
"""


def test_single_line_hunk():
    files = {"config.ini": "[server]\nport = 8080\nhost = 0.0.0.0\n"}
    result = apply_patch(files, PATCH)
    assert result["config.ini"] == "[server]\nport = 9090\nhost = 0.0.0.0\n", result


if __name__ == "__main__":
    test_single_line_hunk()
    print("visible checks passed")
