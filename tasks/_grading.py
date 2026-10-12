"""Hidden-test harness shared by tasks/*/grade.py (stdlib only, Python 3.9+).

grade.py is run as:  python3 -I grade.py <workspace_dir>
It prints one JSON line: {"passed": int, "total": int, "failed": [...], "load_error": str|null}
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys

CASE_TIMEOUT_SEC = 5


class CaseTimeout(BaseException):
    """BaseException이라야 모델 코드의 `except Exception`에 삼켜지지 않는다."""


def _alarm_handler(signum, frame):
    raise CaseTimeout(f"case took longer than {CASE_TIMEOUT_SEC}s")


def _with_timeout(fn, seconds):
    # SIGALRM은 POSIX에만 있다. Windows에서는 전체 채점 타임아웃(run_bench.py)에 맡긴다.
    if not hasattr(signal, "SIGALRM"):
        return fn()
    old = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(seconds)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type:
        return
    except Exception as exc:
        raise AssertionError(f"expected {exc_type.__name__}, got {type(exc).__name__}: {exc}") from None
    raise AssertionError(f"expected {exc_type.__name__}, nothing raised")


def equal(actual, expected):
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")


class Grader:
    def __init__(self, module_name):
        self.module_name = module_name
        self.cases = []

    def case(self, name):
        def register(fn):
            self.cases.append((name, fn))
            return fn
        return register

    def _load(self, workspace):
        # 맨 뒤에 붙여서 작업 폴더의 파일이 표준 라이브러리를 가리지 못하게 한다.
        if workspace not in sys.path:
            sys.path.append(workspace)
        path = os.path.join(workspace, self.module_name + ".py")
        spec = importlib.util.spec_from_file_location(self.module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[self.module_name] = module
        spec.loader.exec_module(module)
        return module

    def main(self):
        workspace = os.path.abspath(sys.argv[1])
        failed = []
        passed = 0
        load_error = None
        try:
            module = _with_timeout(lambda: self._load(workspace), CASE_TIMEOUT_SEC * 2)
        except BaseException as exc:  # SystemExit from model code included
            module = None
            load_error = f"{type(exc).__name__}: {exc}"[:300]
        for name, fn in self.cases:
            if module is None:
                failed.append({"case": name, "why": "module failed to load"})
                continue
            try:
                _with_timeout(lambda: fn(module, workspace), CASE_TIMEOUT_SEC)
                passed += 1
            except KeyboardInterrupt:
                raise
            except BaseException as exc:
                failed.append({"case": name, "why": f"{type(exc).__name__}: {exc}"[:200]})
        print(json.dumps({"passed": passed, "total": len(self.cases),
                          "failed": failed, "load_error": load_error}))
