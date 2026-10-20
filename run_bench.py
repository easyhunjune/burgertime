#!/usr/bin/env python3
"""버거타임 측정기: Claude Code CLI와 Codex CLI의 시간대별 속도·품질을 기록한다.

명령
  selftest   채점기 점검 (쿼터 소모 없음)
  ping       모든 대상에 아주 짧은 프롬프트를 보내 응답 속도를 잰다
  quality    코딩 과제를 풀게 하고 숨은 테스트로 채점한다
  calibrate  quality를 여러 번 돌려 과제 난이도(천장 여부)를 확인한다
  tick       launchd가 주기적으로 부르는 진입점 (ping + 정해진 시각이면 quality)
  status     최근 기록 몇 줄을 보여준다

기록은 results/runs.jsonl 에 한 줄씩 쌓이고, 분석은 analyze.py 로 한다.
표준 라이브러리만 쓰며 Python 3.9 이상에서 동작한다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCH_DIR / "tasks"
RESULTS_DIR = BENCH_DIR / "results"
RUNS_FILE = RESULTS_DIR / "runs.jsonl"
STATE_FILE = RESULTS_DIR / "state.json"
SCHEMA = 1
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache", ".mypy_cache"}

PING_PROMPT = "Reply with exactly one word: pong"
QUALITY_PREAMBLE = (
    "Work autonomously in the current directory; nobody will answer questions. "
    "Only create or modify files inside the current directory. "
    "When you are finished, reply with a one-line summary.\n\n"
)

RATE_LIMIT_RE = re.compile(
    r"usage limit|rate[ _-]?limit|limit reached|quota|too many requests|\b429\b", re.I)
OVERLOAD_RE = re.compile(
    r"overload|at capacity|server_overloaded|\b529\b|\b503\b|temporarily unavailable", re.I)
# 로그인·토큰 문제. 서버 부하와 무관하므로 analyze.py의 서버 오류율에 넣지 않는다.
AUTH_RE = re.compile(
    r"\b401\b|unauthori[sz]ed|authentication[_ ](error|failed)|invalid api key|not logged in"
    r"|please run /login|(oauth )?token (has )?expired|invalid bearer token", re.I)


# ---------------------------------------------------------------- time

def _zone(name, fallback_hours):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:  # tzdata가 없는 환경(일부 Windows)용 근사값
        return dt.timezone(dt.timedelta(hours=fallback_hours))


KST = _zone("Asia/Seoul", 9)
PACIFIC = _zone("America/Los_Angeles", -8)


def time_fields(ts):
    utc = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    kst, pac = utc.astimezone(KST), utc.astimezone(PACIFIC)
    return {
        "started_utc": utc.isoformat(timespec="seconds"),
        "kst_date": kst.date().isoformat(),
        "kst_hour": kst.hour,
        "kst_weekday": kst.weekday(),
        "us_pacific_hour": pac.hour,
        "us_pacific_weekday": pac.weekday(),
    }


def log(msg):
    stamp = dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    print(f"[{stamp}] {msg}", flush=True)


# ---------------------------------------------------------------- files, locks, state

class FileLock:
    """flock(POSIX)/msvcrt(Windows) 기반 잠금. 프로세스가 죽으면 OS가 풀어준다."""

    def __init__(self, path, blocking=True):
        self.path = Path(path)
        self.blocking = blocking
        self.fh = None

    def _try(self, blocking):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def acquire(self, wait_sec=0.0):
        """blocking=False일 때 wait_sec 동안은 0.5초 간격으로 다시 시도한다."""
        if self.blocking:
            return self._try(True)
        deadline = time.monotonic() + wait_sec
        while not self._try(False):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)
        return True

    def release(self):
        if self.fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh, fcntl.LOCK_UN)
        finally:
            self.fh.close()
            self.fh = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"could not lock {self.path}")
        return self

    def __exit__(self, *exc):
        self.release()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def append_record(rec):
    line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    with FileLock(RESULTS_DIR / "runs.lock"):
        with open(RUNS_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _json(line):
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------- config & tasks

def load_config():
    cfg = json.loads((BENCH_DIR / "config.json").read_text(encoding="utf-8"))
    names = [t["name"] for t in cfg["targets"]]
    if len(names) != len(set(names)):
        sys.exit("config.json: target name이 중복됩니다.")
    for t in cfg["targets"]:
        if t["cli"] not in ("claude", "codex"):
            sys.exit(f"config.json: {t['name']}의 cli는 claude 또는 codex여야 합니다.")
    load_env_file(cfg)
    return cfg


# launchd 작업은 로그인 키체인의 Claude 로그인을 못 읽거나 만료된 것을 읽을 수 있다.
# 그래서 `claude setup-token`으로 만든 토큰을 파일에서 읽어 claude 프로세스에만 환경변수로 넘긴다.
# (측정기 전체 환경에 넣으면 codex 실행과 채점기까지 토큰을 물려받는다.) 이 목록에 있는 키만 읽는다.
ENV_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN",)
CLAUDE_ENV = {}


def claude_env():
    """claude를 실행할 때 쓸 환경. 현재 환경에 env_file에서 읽은 키만 더한다."""
    env = dict(os.environ)
    env.update(CLAUDE_ENV)
    return env


def load_env_file(cfg):
    """config의 env_file(KEY=VALUE 형식)에서 ENV_KEYS만 읽어 CLAUDE_ENV에 담는다. 값은 출력하지 않는다.
    이미 환경변수로 설정돼 있는 키는 건드리지 않는다."""
    path = cfg.get("env_file")
    if not path:
        return []
    path = Path(os.path.expanduser(path))
    if not path.is_absolute():
        path = BENCH_DIR / path
    loaded = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return loaded
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or key not in ENV_KEYS or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            CLAUDE_ENV[key] = value
            loaded.append(key)
    cfg["_env_loaded"] = loaded
    return loaded


def select_targets(cfg, names=None, kind=None):
    out = []
    for t in cfg["targets"]:
        if names:
            if t["name"] not in names:
                continue
        elif not t.get("enabled", True):
            continue
        if kind and not t.get(kind, True):
            continue
        out.append(t)
    if names:
        missing = set(names) - {t["name"] for t in out}
        if missing:
            sys.exit(f"config.json에 없는 target: {', '.join(sorted(missing))}")
    return out


def _hash_paths(paths):
    """과제 내용이 바뀌면 task_version이 바뀌도록 파일 내용을 해시한다."""
    files = []
    for path in map(Path, paths):
        if path.is_dir():
            files += sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        else:
            files.append(path)
    h = hashlib.sha1()
    for f in files:
        h.update(str(f.relative_to(TASKS_DIR)).replace("\\", "/").encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:10]


def load_tasks(cfg, only=None):
    tasks = []
    for tid in cfg["tasks"]:
        if only and tid not in only:
            continue
        d = TASKS_DIR / tid
        meta = json.loads((d / "task.json").read_text(encoding="utf-8"))
        meta["dir"] = d
        meta["version"] = _hash_paths([d / "workspace", d / "grade.py", d / "task.json",
                                       TASKS_DIR / "_grading.py"])
        tasks.append(meta)
    if only:
        missing = set(only) - {t["id"] for t in tasks}
        if missing:
            sys.exit(f"config.json tasks에 없는 과제: {', '.join(sorted(missing))}")
    return tasks


# ---------------------------------------------------------------- processes

def _kill_group(proc, sig):
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def kill_tree(proc):
    if os.name == "posix":
        _kill_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_group(proc, signal.SIGKILL)
    else:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_process(cmd, cwd, stdin_text, timeout, env=None):
    """stdout 줄마다 시작 후 경과 시간을 붙여 모은다. env가 None이면 현재 환경을 물려준다."""
    t0 = time.monotonic()
    extra = {"start_new_session": True} if os.name == "posix" else {}
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, **extra)
    except OSError as exc:
        return {"exit_code": None, "timed_out": False, "wall_sec": 0.0, "lines": [],
                "stderr": f"failed to start {cmd[0]}: {exc}"}
    lines, err = [], bytearray()

    def read_out():
        for raw in proc.stdout:
            lines.append((round(time.monotonic() - t0, 3),
                          raw.decode("utf-8", "replace").rstrip("\r\n")))

    def read_err():
        err.extend(proc.stderr.read())

    readers = [threading.Thread(target=read_out, daemon=True),
               threading.Thread(target=read_err, daemon=True)]
    for th in readers:
        th.start()
    try:
        proc.stdin.write(stdin_text.encode("utf-8"))
        proc.stdin.close()
    except OSError:
        pass
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
    if os.name == "posix":  # 남은 자식 프로세스 정리
        _kill_group(proc, signal.SIGTERM)
    for th in readers:
        th.join(timeout=10)
    return {"exit_code": proc.returncode, "timed_out": timed_out,
            "wall_sec": round(time.monotonic() - t0, 3), "lines": lines,
            "stderr": err.decode("utf-8", "replace")}


def classify(timed_out, ok, text, http_status=None, rl_rejected=False):
    if timed_out:
        return "timeout"
    if ok:
        return "ok"
    if http_status in (401, 403) or AUTH_RE.search(text or ""):
        return "auth_error"
    if rl_rejected or http_status == 429 or RATE_LIMIT_RE.search(text or ""):
        return "rate_limited"
    if http_status in (500, 502, 503, 504, 529) or OVERLOAD_RE.search(text or ""):
        return "overloaded"
    return "cli_error"


# ---------------------------------------------------------------- Claude Code

# --safe-mode도 사용자 settings.json의 advisorModel은 그대로 적용한다. 그러면 측정 대상 모델이
# 과제 중에 다른 모델(advisor)에게 조언을 받아 시간·토큰이 섞이므로, 빈 문자열로 덮어써 끈다.
CLAUDE_SETTINGS = json.dumps({"advisorModel": ""})


def claude_cmd(target, kind):
    exe = target.get("bin") or shutil.which("claude") or "claude"
    cmd = [exe, "-p", "--safe-mode", "--settings", CLAUDE_SETTINGS,
           "--no-session-persistence", "--permission-prompts", "none",
           "--output-format", "stream-json", "--verbose", "--model", target["model"]]
    effort = target.get("ping_effort") if kind == "ping" else target.get("effort")
    if effort:
        cmd += ["--effort", effort]
    if kind == "ping":
        cmd += ["--tools", ""]
    else:
        cmd += ["--permission-mode", "acceptEdits",
                "--allowedTools", "Bash(python3 *)", "Bash(python *)"]
    return cmd + list(target.get("extra_args", []))


def parse_claude(res):
    init_model = version = result = rl = None
    served = Counter()
    first_t = None
    tool_calls = thinking_chars = advisor_calls = 0
    for t, line in res["lines"]:
        j = _json(line)
        if j is None:
            continue
        typ = j.get("type")
        if typ == "system" and j.get("subtype") == "init":
            init_model, version = j.get("model"), j.get("claude_code_version")
        elif typ == "assistant" and not j.get("parent_tool_use_id"):
            msg = j.get("message") or {}
            served[msg.get("model") or "?"] += 1
            if first_t is None:
                first_t = t
            for block in msg.get("content") or []:
                if block.get("type") == "tool_use":
                    tool_calls += 1
                elif block.get("type") == "server_tool_use" and block.get("name") == "advisor":
                    advisor_calls += 1
                elif block.get("type") == "thinking":
                    thinking_chars += len(block.get("thinking") or "")
        elif typ == "rate_limit_event":
            rl = j.get("rate_limit_info") or rl
        elif typ == "result":
            result = j

    result = result or {}
    usage = result.get("usage") or {}
    model_usage = result.get("modelUsage") or {}
    real_models = {m: n for m, n in served.items() if m not in ("<synthetic>", "?")}
    served_model = max(real_models, key=real_models.get) if real_models else None
    # 응답 메시지에는 안 보이지만 사용량에는 잡히는 모델 (advisor, 하위 에이전트 등)
    main_model = init_model or served_model
    extra_models = sorted(m for m in model_usage if main_model and m != main_model)
    windows = (rl or {}).get("unifiedWindows") or {}
    out_tokens = sum(int(v.get("outputTokens") or 0) for v in model_usage.values())
    thinking = sum(int(v.get("thinkingTokens") or 0) for v in model_usage.values())
    if not thinking:
        thinking = (usage.get("output_tokens_details") or {}).get("thinking_tokens")

    ok = (res["exit_code"] == 0 and result.get("subtype") == "success"
          and not result.get("is_error"))
    err_text = "" if ok else f"{result.get('result') or ''}\n{res['stderr'][-2000:]}"
    http = result.get("api_error_status")
    status = classify(res["timed_out"], ok, err_text, http,
                      (rl or {}).get("status") == "rejected")
    return {
        "status": status,
        "error": None if ok else err_text.strip()[:300],
        "cli_version": version,
        "resolved_model": init_model,
        "served_models": dict(served),
        "served_model": served_model,
        "model_mismatch": bool(init_model and any(m != init_model for m in real_models)),
        "extra_models": extra_models,
        "advisor_calls": advisor_calls,
        "served_effort": None,
        "t_first_output_sec": first_t,
        "ttft_ms": result.get("ttft_ms"),
        "duration_api_ms": result.get("duration_api_ms"),
        "num_turns": result.get("num_turns"),
        "tool_calls": tool_calls,
        "output_tokens": out_tokens or usage.get("output_tokens"),
        "thinking_tokens": thinking,
        "thinking_chars": thinking_chars,
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "cost_usd_list": result.get("total_cost_usd"),
        "inference_geo": usage.get("inference_geo"),
        "service_tier": usage.get("service_tier"),
        "speed": usage.get("speed"),
        "terminal_reason": result.get("terminal_reason"),
        "api_error_status": http,
        "permission_denials": len(result.get("permission_denials") or []),
        "subagents_spawned": (result.get("subagent_stats") or {}).get("spawned"),
        "rl_status": (rl or {}).get("status"),
        "rl_5h_util": (windows.get("five_hour") or {}).get("utilization"),
        "rl_7d_util": (windows.get("seven_day") or {}).get("utilization"),
        "plan_type": None,
        "final_text": (result.get("result") or "")[:300],
    }


# ---------------------------------------------------------------- Codex

def codex_cmd(cfg, target, kind, cwd):
    exe = target.get("bin") or shutil.which("codex") or "codex"
    cmd = [exe, "exec", "--json", "--skip-git-repo-check",
           "-s", "read-only" if kind == "ping" else "workspace-write",
           "-m", target["model"], "-c", 'approval_policy="never"', "-C", str(cwd)]
    if cfg.get("codex_ignore_user_config", True):
        cmd += ["--ignore-user-config", "--ignore-rules"]
    # config.toml을 무시하는 대신, 측정에 꼭 필요한 키만 여기로 넘긴다.
    # 예) Windows: 'windows.sandbox="elevated"'  (macOS는 기본 샌드박스라 필요 없음)
    for override in cfg.get("codex_config_overrides", []):
        cmd += ["-c", override]
    effort = target.get("ping_effort") if kind == "ping" else target.get("effort")
    if effort:
        cmd += ["-c", f'model_reasoning_effort="{effort}"']
    return cmd + list(target.get("extra_args", [])) + ["-"]


_codex_version_cache = {}


def codex_version(exe):
    if exe not in _codex_version_cache:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, timeout=30)
            _codex_version_cache[exe] = out.stdout.decode("utf-8", "replace").strip().split()[-1]
        except Exception:
            _codex_version_cache[exe] = None
    return _codex_version_cache[exe]


def read_codex_rollout(thread_id):
    """세션 로그(rollout)에서 클라이언트가 실제로 쓴 모델·effort와 사용량 한도를 읽는다."""
    if not thread_id:
        return {}
    sessions = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"
    found = []
    today = dt.date.today()
    for delta in (0, -1, 1):
        d = today + dt.timedelta(days=delta)
        found += list((sessions / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}").glob(f"rollout-*{thread_id}.jsonl"))
    if not found:
        found = list(sessions.glob(f"*/*/*/rollout-*{thread_id}.jsonl"))
    if not found:
        return {"rollout_found": False}
    models, efforts, cli_version, rates = Counter(), Counter(), None, None
    with open(found[0], encoding="utf-8", errors="replace") as fh:
        for line in fh:
            j = _json(line)
            if j is None:
                continue
            payload = j.get("payload") or {}
            if j.get("type") == "session_meta":
                cli_version = payload.get("cli_version")
            elif j.get("type") == "turn_context":
                models[payload.get("model")] += 1
                efforts[payload.get("effort")] += 1
            elif (j.get("type") == "event_msg" and payload.get("type") == "token_count"
                  and payload.get("rate_limits")):
                rates = payload["rate_limits"]
    rates = rates or {}

    def used(window):
        pct = (rates.get(window) or {}).get("used_percent")
        return None if pct is None else round(pct / 100.0, 4)

    return {
        "rollout_found": True,
        "rollout_models": dict(models),
        "rollout_efforts": dict(efforts),
        "cli_version": cli_version,
        "rl_5h_util": used("primary"),
        "rl_7d_util": used("secondary"),
        "plan_type": rates.get("plan_type"),
        "rl_reached": rates.get("rate_limit_reached_type"),
        "rl_limit_id": rates.get("limit_id"),
        "rl_limit_name": rates.get("limit_name"),
    }


def parse_codex(res, target, exe):
    thread_id = first_t = None
    usage, items = Counter(), Counter()
    errors, final_text = [], ""
    completed = failed = False
    for t, line in res["lines"]:
        j = _json(line)
        if j is None:
            continue
        typ = j.get("type")
        if typ == "thread.started":
            thread_id = j.get("thread_id")
        elif typ == "item.completed":
            item = j.get("item") or {}
            items[item.get("type")] += 1
            if first_t is None:
                first_t = t
            if item.get("type") == "agent_message":
                final_text = item.get("text") or final_text
            elif item.get("type") == "error":
                errors.append(str(item.get("message"))[:300])
        elif typ == "turn.completed":
            completed = True
            for k, v in (j.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    usage[k] += v
        elif typ == "turn.failed":
            failed = True
            errors.append(json.dumps(j.get("error"), ensure_ascii=False)[:300])
        elif typ == "error":
            errors.append(str(j.get("message"))[:300])

    roll = read_codex_rollout(thread_id)
    models = roll.get("rollout_models") or {}
    efforts = roll.get("rollout_efforts") or {}
    served_model = max(models, key=models.get) if models else None
    served_effort = max(efforts, key=efforts.get) if efforts else None
    ok = res["exit_code"] == 0 and completed and not failed
    err_text = "" if ok else "\n".join(errors) + "\n" + res["stderr"][-2000:]
    status = classify(res["timed_out"], ok, err_text, None, bool(roll.get("rl_reached")))
    return {
        "status": status,
        "error": None if ok else err_text.strip()[:300],
        "transient_errors": len(errors) if ok else None,
        "cli_version": roll.get("cli_version") or codex_version(exe),
        "thread_id": thread_id,
        "resolved_model": target["model"],
        "served_models": models,
        "served_model": served_model,
        "model_mismatch": bool(served_model and any(m != target["model"] for m in models)),
        "served_effort": served_effort,
        "rollout_found": roll.get("rollout_found"),
        "t_first_output_sec": first_t,
        "ttft_ms": None,
        "duration_api_ms": None,
        "num_turns": items.get("agent_message"),
        "tool_calls": items.get("command_execution", 0) + items.get("file_change", 0),
        "items": dict(items),
        "output_tokens": usage.get("output_tokens"),
        "thinking_tokens": usage.get("reasoning_output_tokens"),
        "input_tokens": usage.get("input_tokens"),
        "cached_input_tokens": usage.get("cached_input_tokens"),
        "cache_write_tokens": usage.get("cache_write_input_tokens"),
        "rl_status": roll.get("rl_reached"),
        "rl_5h_util": roll.get("rl_5h_util"),
        "rl_7d_util": roll.get("rl_7d_util"),
        "plan_type": roll.get("plan_type"),
        "rl_limit_id": roll.get("rl_limit_id"),
        "rl_limit_name": roll.get("rl_limit_name"),
        "final_text": final_text[:300],
    }


# ---------------------------------------------------------------- one measurement

def build_and_run(cfg, target, kind, cwd, prompt, timeout):
    if target["cli"] == "claude":
        res = run_process(claude_cmd(target, kind), cwd, prompt, timeout, env=claude_env())
        return res, parse_claude(res)
    cmd = codex_cmd(cfg, target, kind, cwd)
    res = run_process(cmd, cwd, prompt, timeout)
    return res, parse_codex(res, target, cmd[0])


def base_record(kind, run_id, target, started, ctx, task=None):
    effort_key = "ping_effort" if kind == "ping" else "effort"
    rec = {
        "schema": SCHEMA,
        "kind": kind,
        "run_id": run_id,
        "trigger": ctx.get("trigger", "manual"),
        "target": target["name"],
        "cli": target["cli"],
        "requested_model": target["model"],
        "requested_effort": target.get(effort_key),
        "task": task["id"] if task else None,
        "task_version": task["version"] if task else None,
        "gap_since_prev_tick_sec": ctx.get("gap_sec"),
        "after_gap": bool(ctx.get("after_gap")),
        "bench_platform": sys.platform,
    }
    rec.update(time_fields(started))
    return rec


def save_raw(run_id, name, res, workspace=None, files=None):
    """원본 출력을 남긴다. workspace와 snapshot()의 files를 주면 작은 작업 폴더는 zip으로 보관한다."""
    day = dt.datetime.now(KST).date().isoformat()
    d = RESULTS_DIR / "raw" / day / run_id
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / f"{name}.stdout.jsonl.gz", "wt", encoding="utf-8") as fh:
        for t, line in res["lines"]:
            fh.write(json.dumps({"t": t, "l": line}, ensure_ascii=False) + "\n")
    if res["stderr"].strip():
        (d / f"{name}.stderr.txt").write_text(res["stderr"][-20000:], encoding="utf-8")
    if workspace is not None and files and sum(size for size, _ in files.values()) < 2_000_000:
        with zipfile.ZipFile(d / f"{name}.workspace.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for rel in sorted(files):
                zf.write(os.path.join(workspace, rel), rel)
    return str(d.relative_to(BENCH_DIR)).replace("\\", "/")


def grade_workspace(task, workspace):
    cmd = [sys.executable, "-I", "-B", str(task["dir"] / "grade.py"), str(workspace)]
    try:
        out = subprocess.run(cmd, cwd=str(workspace), capture_output=True, timeout=300)
        report = json.loads(out.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"score": 0.0, "passed": 0, "total": None, "failed_cases": None,
                "grade_error": "grader timeout (300s)"}
    except Exception as exc:
        return {"score": None, "passed": None, "total": None, "failed_cases": None,
                "grade_error": f"grader crashed: {exc}"[:300]}
    total = report["total"] or 1
    return {"score": round(report["passed"] / total, 4), "passed": report["passed"],
            "total": report["total"], "failed_cases": [f["case"] for f in report["failed"]],
            "grade_error": report.get("load_error")}


def measure_ping(cfg, target, ctx, run_id):
    cwd = Path(tempfile.mkdtemp(prefix="bt_ping_"))
    started = time.time()
    try:
        res, parsed = build_and_run(cfg, target, "ping", cwd, PING_PROMPT,
                                    cfg.get("ping_timeout_sec", 180))
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    rec = base_record("ping", run_id, target, started, ctx)
    rec.update(parsed)
    rec["wall_sec"] = res["wall_sec"]
    rec["exit_code"] = res["exit_code"]
    rec["timed_out"] = res["timed_out"]
    rec["answer_ok"] = "pong" in (parsed.get("final_text") or "").lower()
    # 과제 실행과 겹친 ping은 같은 계정에 요청이 몰린 상태라 analyze.py가 기본으로 뺀다.
    rec["quality_running"] = bool(ctx.get("quality_running"))
    if cfg.get("keep_raw", True) and rec["status"] != "ok":
        rec["raw_path"] = save_raw(run_id, f"{target['name']}__ping", res)
    append_record(rec)
    log(f"ping {target['name']}: {rec['status']} first={rec['t_first_output_sec']}s "
        f"wall={rec['wall_sec']}s model={rec.get('served_model')}"
        + (f"  (다른 모델 사용: {rec['extra_models']})" if rec.get("extra_models") else ""))
    return rec


def snapshot(folder):
    """파일별 (크기, 수정시각). 내용은 읽지 않으므로 에이전트가 큰 폴더를 만들어도 싸다.
    copytree가 원본 수정시각을 유지하므로, 에이전트가 고친 파일은 수정시각이 달라진다."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            files[os.path.relpath(path, folder)] = (st.st_size, st.st_mtime_ns)
    return files


def measure_task(cfg, target, task, ctx, run_id):
    ws = Path(tempfile.mkdtemp(prefix=f"bt_{task['id']}_"))
    shutil.copytree(task["dir"] / "workspace", ws, dirs_exist_ok=True, ignore=IGNORE)
    before = snapshot(ws)
    started = time.time()
    try:
        res, parsed = build_and_run(cfg, target, "quality", ws, QUALITY_PREAMBLE + task["prompt"],
                                    cfg.get("task_timeout_sec", 900))
        after = snapshot(ws)
        grade = grade_workspace(task, ws)
        rec = base_record("quality", run_id, target, started, ctx, task)
        rec.update(parsed)
        rec.update(grade)
        # 파일을 하나도 안 건드렸다면 권한·샌드박스 문제일 가능성이 크다. 점수 저하로 오인하지 않게 표시한다.
        rec["files_changed"] = sum(before.get(k) != v for k, v in after.items()) + \
            sum(k not in after for k in before)
        rec["workspace_changed"] = rec["files_changed"] > 0
        rec["wall_sec"] = res["wall_sec"]
        rec["exit_code"] = res["exit_code"]
        rec["timed_out"] = res["timed_out"]
        if cfg.get("keep_raw", True):
            rec["raw_path"] = save_raw(run_id, f"{target['name']}__{task['id']}", res, ws, after)
    finally:
        shutil.rmtree(ws, ignore_errors=True)
    append_record(rec)
    log(f"quality {target['name']} {task['id']}: {rec['status']} score={rec['score']} "
        f"({rec['passed']}/{rec['total']}) wall={rec['wall_sec']}s "
        f"thinking={rec.get('thinking_tokens')} model={rec.get('served_model')}"
        + ("" if rec["workspace_changed"] else "  (파일 변경 없음!)")
        + (f"  (다른 모델 사용: {rec['extra_models']})" if rec.get("extra_models") else ""))
    return rec


def _error_record(kind, run_id, target, ctx, exc, task=None):
    rec = base_record(kind, run_id, target, time.time(), ctx, task)
    rec.update({"status": "bench_error", "error": f"{type(exc).__name__}: {exc}"[:300]})
    append_record(rec)
    log(f"{kind} {target['name']}: bench_error {exc}")
    return rec


def by_cli_in_parallel(targets, work):
    """CLI(=회사)마다 스레드 하나. 같은 CLI 대상끼리는 순서대로 돈다."""
    groups = {}
    for t in targets:
        groups.setdefault(t["cli"], []).append(t)
    threads = [threading.Thread(target=lambda ts=ts: [work(t) for t in ts]) for ts in groups.values()]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


def run_pings(cfg, targets, ctx):
    run_id = dt.datetime.now(KST).strftime("%Y%m%dT%H%M") + "-p-" + uuid.uuid4().hex[:6]
    records = []

    def work(target):
        try:
            records.append(measure_ping(cfg, target, ctx, run_id))
        except Exception as exc:
            records.append(_error_record("ping", run_id, target, ctx, exc))

    by_cli_in_parallel(targets, work)
    return records


def run_quality(cfg, targets, tasks, ctx):
    run_id = dt.datetime.now(KST).strftime("%Y%m%dT%H%M") + "-q-" + uuid.uuid4().hex[:6]
    records = []

    def work(target):
        order = tasks[:]
        random.shuffle(order)  # 과제 순서 효과를 없앤다
        for task in order:
            try:
                records.append(measure_task(cfg, target, task, ctx, run_id))
            except Exception as exc:
                records.append(_error_record("quality", run_id, target, ctx, exc, task))

    by_cli_in_parallel(targets, work)
    return records


# ---------------------------------------------------------------- commands

def cmd_selftest(cfg, args):
    ok = True
    print("과제 채점기 점검 (모델 호출 없음)")
    for task in load_tasks(cfg):
        for label, overlay, want_full in (("starter", None, False),
                                          ("reference", task["dir"] / "reference", True)):
            ws = Path(tempfile.mkdtemp(prefix="bt_selftest_"))
            try:
                shutil.copytree(task["dir"] / "workspace", ws, dirs_exist_ok=True, ignore=IGNORE)
                if overlay:
                    shutil.copytree(overlay, ws, dirs_exist_ok=True)
                g = grade_workspace(task, ws)
            finally:
                shutil.rmtree(ws, ignore_errors=True)
            good = g["total"] is not None and (
                g["passed"] == g["total"] if want_full else g["passed"] < g["total"])
            ok &= good
            print(f"  {'OK ' if good else 'BAD'} {task['id']:<14} {label:<9} "
                  f"{g['passed']}/{g['total']}" + (f"  ({g['grade_error']})" if g["grade_error"] and want_full else ""))
    print("\nCLI 확인")
    if cfg.get("env_file"):
        loaded = cfg.get("_env_loaded") or []
        token = "있음" if claude_env().get("CLAUDE_CODE_OAUTH_TOKEN") else "없음"
        print(f"  env_file {cfg['env_file']}: 읽은 키 {loaded or '없음'} / CLAUDE_CODE_OAUTH_TOKEN {token}")
    for target in select_targets(cfg):
        exe = target.get("bin") or shutil.which(target["cli"])
        if exe and not os.path.exists(exe) and not shutil.which(exe):
            exe = None
        if not exe:
            ok = False
            print(f"  BAD {target['name']}: '{target['cli']}' 실행 파일을 PATH에서 못 찾음")
            continue
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, timeout=30)
            ver = out.stdout.decode("utf-8", "replace").strip()
        except Exception as exc:
            ver = f"version check failed: {exc}"
        print(f"  OK  {target['name']}: {exe} ({ver})")
    print("\n결과:", "통과" if ok else "실패")
    return 0 if ok else 1


QUALITY_LOCK = RESULTS_DIR / "quality.lock"


def quality_running():
    """quality 잠금이 잡혀 있으면 과제가 도는 중이다. 잠깐 잡았다 놓기만 한다.
    (그 찰나에 시작하는 quality 프로세스는 acquire(wait_sec)로 기다리므로 밀려나지 않는다.)"""
    probe = FileLock(QUALITY_LOCK, blocking=False)
    if probe.acquire():
        probe.release()
        return False
    return True


def cmd_ping(cfg, args):
    RESULTS_DIR.mkdir(exist_ok=True)
    ctx = {"trigger": args.trigger, "quality_running": quality_running()}
    recs = run_pings(cfg, select_targets(cfg, args.target, "ping"), ctx)
    return 0 if all(r["status"] == "ok" for r in recs) else 1


def cmd_quality(cfg, args):
    RESULTS_DIR.mkdir(exist_ok=True)
    lock = FileLock(QUALITY_LOCK, blocking=False)
    if not lock.acquire(wait_sec=15):
        log("quality: 이전 quality 실행이 아직 진행 중이라 건너뜀")
        return 0
    try:
        if args.epoch_hour is not None:
            # 실제로 시작했을 때만 이 시간대를 '측정함'으로 남긴다. 실패하면 다음 tick이 다시 띄운다.
            with FileLock(RESULTS_DIR / "state.lock"):
                state = load_state()
                state["last_quality_epoch_hour"] = args.epoch_hour
                save_state(state)
        ctx = {"trigger": args.trigger, "gap_sec": args.gap_sec, "after_gap": args.after_gap}
        targets = select_targets(cfg, args.target, "quality")
        tasks = load_tasks(cfg, args.task)
        log(f"quality 시작: {[t['name'] for t in targets]} x {[t['id'] for t in tasks]}")
        run_quality(cfg, targets, tasks, ctx)
    finally:
        lock.release()
    return 0


def cmd_calibrate(cfg, args):
    RESULTS_DIR.mkdir(exist_ok=True)
    targets = select_targets(cfg, args.target, "quality")
    tasks = load_tasks(cfg, args.task)
    lock = FileLock(QUALITY_LOCK, blocking=False)
    if not lock.acquire(wait_sec=15):
        print("다른 quality 실행이 진행 중입니다. 끝난 뒤 다시 실행하세요.")
        return 1
    scores = {}
    try:
        for i in range(args.repeat):
            log(f"calibrate {i + 1}/{args.repeat}")
            for rec in run_quality(cfg, targets, tasks, {"trigger": "calibrate"}):
                scores.setdefault((rec["target"], rec.get("task")), []).append(rec)
    finally:
        lock.release()
    print("\n대상            과제            점수들            thinking 토큰     소요(초)      "
          "변경파일  권한거부")
    for (target, task), recs in sorted(scores.items()):
        s = " ".join("-" if r.get("score") is None else f"{r['score']:.2f}" for r in recs)
        th = " ".join(str(r.get("thinking_tokens")) for r in recs)
        w = " ".join(str(round(r.get("wall_sec") or 0)) for r in recs)
        fc = " ".join(str(r.get("files_changed")) for r in recs)
        pd = " ".join(str(r.get("permission_denials")) for r in recs)
        print(f"{target:<15} {task or '-':<15} {s:<17} {th:<17} {w:<13} {fc:<9} {pd}")
    denied = [r for recs in scores.values() for r in recs if r.get("permission_denials")]
    if denied:
        print(f"\n경고: 도구 사용이 거부된 실행이 {len(denied)}건 있습니다 (Claude가 python3로 테스트를 못 돌렸을 수 있음)."
              " results/raw 의 stdout에서 permission_denials 를 확인하세요.")
    untouched = [r for recs in scores.values() for r in recs
                 if r.get("status") == "ok" and r.get("workspace_changed") is False]
    if untouched:
        print(f"\n경고: 파일을 하나도 안 고친 실행이 {len(untouched)}건 있습니다. "
              "results/raw 의 stderr를 보고 권한·샌드박스 문제인지 확인하세요.")
    print("\n점수가 계속 1.00이면 그 과제는 천장입니다. 그래도 thinking 토큰·소요 시간 변화는 볼 수 있지만,"
          "\n정답률 차이를 보려면 0.5~0.9 정도가 나오는 과제가 좋습니다.")
    return 0


def spawn_quality(ctx, epoch_hour):
    cmd = [sys.executable, str(Path(__file__).resolve()), "quality", "--trigger", "schedule",
           "--epoch-hour", str(epoch_hour)]
    if ctx.get("gap_sec") is not None:
        cmd += ["--gap-sec", str(ctx["gap_sec"])]
    if ctx.get("after_gap"):
        cmd.append("--after-gap")
    if sys.platform == "darwin" and os.path.exists("/usr/bin/caffeinate"):
        cmd = ["/usr/bin/caffeinate", "-i"] + cmd  # 과제가 도는 동안 유휴 잠자기 방지
    extra = {"start_new_session": True} if os.name == "posix" else {}
    with open(RESULTS_DIR / "quality.log", "ab") as logfile:
        subprocess.Popen(cmd, cwd=str(BENCH_DIR), stdin=subprocess.DEVNULL, stdout=logfile,
                         stderr=subprocess.STDOUT, **extra)
    log("quality 실행을 백그라운드로 띄움")


def cmd_tick(cfg, args):
    RESULTS_DIR.mkdir(exist_ok=True)
    now = time.time()
    epoch_hour = int(now // 3600)
    with FileLock(RESULTS_DIR / "state.lock"):
        state = load_state()
        prev = state.get("last_tick_ts")
        state["last_tick_ts"] = now
        save_state(state)
    gap = None if prev is None else round(now - prev, 1)
    # 맥이 잠들었다 깨면 launchd가 밀린 실행을 한 번에 돌린다. 그런 기록은 표시해 둔다.
    after_gap = gap is not None and gap > cfg["ping_interval_min"] * 60 * 1.5 + 300
    running = quality_running()
    ctx = {"trigger": "schedule", "gap_sec": gap, "after_gap": after_gap, "quality_running": running}

    ping_lock = FileLock(RESULTS_DIR / "ping.lock", blocking=False)
    if ping_lock.acquire():
        try:
            run_pings(cfg, select_targets(cfg, None, "ping"), ctx)
        finally:
            ping_lock.release()
    else:
        log("ping: 이전 ping이 아직 진행 중이라 건너뜀")

    # last_quality_epoch_hour는 quality 프로세스가 실제로 시작했을 때 기록한다.
    # 그래서 띄우기에 실패하거나 이전 실행이 아직 돌고 있으면, 같은 시간대의 다음 tick이 다시 시도한다.
    every = int(cfg.get("quality_every_hours", 0))
    due = (every > 0 and epoch_hour % every == 0 and not running
           and load_state().get("last_quality_epoch_hour") != epoch_hour)
    if due:
        try:
            spawn_quality(ctx, epoch_hour)
        except OSError as exc:
            log(f"quality 실행을 띄우지 못함: {exc}")
    return 0


def cmd_status(cfg, args):
    if not RUNS_FILE.exists():
        print("아직 기록이 없습니다.")
        return 0
    lines = RUNS_FILE.read_text(encoding="utf-8").splitlines()[-args.n:]
    for line in lines:
        r = _json(line) or {}
        when = dt.datetime.fromisoformat(r["started_utc"]).astimezone(KST).strftime("%m-%d %H:%M")
        score = "" if r.get("score") is None else f" score={r['score']:.2f}"
        print(f"{when} KST {r.get('kind'):<7} {r.get('target'):<14} {r.get('task') or '':<14} "
              f"{r.get('status'):<12} wall={r.get('wall_sec')}s{score} model={r.get('served_model')}"
              + (" MISMATCH" if r.get("model_mismatch") else "")
              + (f" EXTRA={r['extra_models']}" if r.get("extra_models") else ""))
    state = load_state()
    if state.get("last_tick_ts"):
        last = dt.datetime.fromtimestamp(state["last_tick_ts"], KST).strftime("%m-%d %H:%M")
        print(f"\n마지막 tick: {last} KST")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="버거타임 측정기")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest", help="채점기와 CLI 점검 (쿼터 소모 없음)")
    p = sub.add_parser("ping", help="응답 속도 측정")
    p.add_argument("--target", action="append")
    p.add_argument("--trigger", default="manual")
    q = sub.add_parser("quality", help="코딩 과제 품질 측정")
    q.add_argument("--target", action="append")
    q.add_argument("--task", action="append")
    q.add_argument("--trigger", default="manual")
    q.add_argument("--gap-sec", type=float, default=None)
    q.add_argument("--after-gap", action="store_true")
    q.add_argument("--epoch-hour", type=int, default=None, help=argparse.SUPPRESS)
    c = sub.add_parser("calibrate", help="과제 난이도 확인 (quality를 여러 번)")
    c.add_argument("--target", action="append")
    c.add_argument("--task", action="append")
    c.add_argument("--repeat", type=int, default=2)
    sub.add_parser("tick", help="launchd 진입점")
    s = sub.add_parser("status", help="최근 기록 보기")
    s.add_argument("-n", type=int, default=12)
    args = parser.parse_args(argv)
    cfg = load_config()
    handler = {"selftest": cmd_selftest, "ping": cmd_ping, "quality": cmd_quality,
               "calibrate": cmd_calibrate, "tick": cmd_tick, "status": cmd_status}[args.command]
    return handler(cfg, args)


if __name__ == "__main__":
    sys.exit(main())
