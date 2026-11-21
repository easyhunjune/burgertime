#!/usr/bin/env python3
"""버거타임 분석: results/runs.jsonl 을 한국 시간대별로 묶고, 버거타임과 나머지 시간을 비교한다.

  python3 analyze.py                      # 기본: 한국시간 01~06시를 버거타임으로
  python3 analyze.py --burger 0-5         # 구간 바꾸기 (22-3처럼 자정을 넘겨도 됨)
  python3 analyze.py --since 2026-10-20   # 특정 날짜 이후만 (CLI 업데이트 이후만 보고 싶을 때)
  python3 analyze.py --since "2026-10-13 09:00" --until "2026-11-10 09:00"   # 시각(KST) 단위 구간
  python3 analyze.py --csv out.csv        # 걸러진 기록을 CSV로 내보내기
  python3 analyze.py --since ... --until ... --verdict round1   # 사전 등록 규칙으로 판정표까지 출력
  python3 analyze.py --score-timeouts      # 과제 제한시간에 걸린 실행도 그 시점 산출물 점수로 포함 (2차용)
  python3 analyze.py --regrade results/regrade.jsonl   # 나중에 다시 채점한 점수(중앙값)로 바꿔서 분석
  python3 analyze.py ... --drop-active-pings   # 민감도 분석: 그 사이 계정이 쓰인 ping(5시간 사용량 3%p 이상 증가)을 빼고 다시 분석

신뢰구간은 클러스터 부트스트랩으로 구한다. 한 번의 과제 실행(run_id)에서 나온 기록들, 같은 날의 ping들은
서로 묶여 움직이므로 기록 하나하나를 독립 표본으로 치면 구간이 실제보다 좁아진다.
그래서 quality는 실행 단위, ping은 날짜 단위로 통째로 다시 뽑는다. 최소 표본 수(--min-n)도 이 묶음 수 기준이다.
구간이 0(차이) 또는 1.00x(비율)을 포함하지 않으면 '유의'로 표시한다.

옵션을 주지 않으면 1차 공개 때와 똑같은 출력이 나온다(data/round1/analysis_*.txt). 새 기능은 모두 옵션으로 켜고,
--verdict의 추가 계산은 기존 출력이 끝난 뒤 별도 난수로 하므로 기존 신뢰구간 숫자를 바꾸지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
# 서버 쪽 문제로 볼 수 있는 실패. rate_limited는 내 사용량에 따라 생기므로 버거타임 판단에서 뺀다.
SERVER_ERRORS = ("overloaded", "timeout", "cli_error")
# 측정 조건이 깨진 구간 (cli, kind, 시작 KST, 끝 KST(미포함), 이유). README 변경 기록과 같이 관리한다.
# 이 구간 기록에는 extra_models 필드가 없어서 시각으로 뺀다.
BROKEN_WINDOWS = [
    ("claude", "quality", "2026-10-18 21:25", "2026-10-21 01:23",
     "Claude advisor(다른 모델 조언)가 섞인 과제 실행"),
]
CODEX_THINKING_NOTE = ("Codex의 thinking 토큰(reasoning_output_tokens)은 실제 추론량보다 훨씬 작게 찍힙니다"
                       " (예: high effort 95초 과제에 146). 참고용으로만 보세요.")

# --score-timeouts: 과제의 제한시간 도달(timeout)을 "그 시점까지의 산출물"로 보고 점수·시간·thinking에 포함한다.
# 1차 규칙(기본값)은 성공(ok)만 쓴다. 2차는 제한시간에 걸리는 과제가 많아서 빼면 느린 실행만 골라 빠진다.
SCORE_TIMEOUTS = False
# --verdict 계산에서 쓰려고 기존 비교 줄의 결과를 모아 둔다. 출력과 난수 사용 순서는 그대로다.
RESULTS = {}

# 사전 등록한 판정 지표: (CLI, 종류, analyze 출력 줄 이름, 값, 비교 방식, 의미 있는 최소 크기 (아래, 위))
# 비교 방식 ratio는 버거타임 중앙값 / 나머지 중앙값, diff는 평균 차이(비율 단위, 0.02 = 2%p).
VERDICT_SETS = {
    "round1": [
        ("claude", "ping", "첫 응답 시간 (중앙값 비)", "t_first_output_sec", "ratio", (0.91, 1.10)),
        ("codex", "ping", "첫 응답 시간 (중앙값 비)", "t_first_output_sec", "ratio", (0.91, 1.10)),
        ("claude", "ping", "서버 오류율 차이", "_server_error", "diff", (-0.02, 0.02)),
        ("codex", "ping", "서버 오류율 차이", "_server_error", "diff", (-0.02, 0.02)),
        ("claude", "quality", "소요 시간 (중앙값 비)", "wall_sec", "ratio", (0.91, 1.10)),
        ("codex", "quality", "소요 시간 (중앙값 비)", "wall_sec", "ratio", (0.91, 1.10)),
        ("claude", "quality", "thinking 토큰 (중앙값 비)", "_thinking", "ratio", (0.85, 1.18)),
    ],
}


def parse_hours(spec):
    hours = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = (int(x) for x in part.split("-"))
            h = a
            while True:
                hours.add(h % 24)
                if h % 24 == b % 24:
                    break
                h += 1
        else:
            hours.add(int(part) % 24)
    return hours


def load(path):
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    return recs


def util_of(r):
    vals = [v for v in (r.get("rl_5h_util"), r.get("rl_7d_util")) if isinstance(v, (int, float))]
    return max(vals) if vals else None


def hour_of(r):
    """버거타임 여부를 정하는 한국 시각. 과제는 예정 시각(slot_kst_hour)으로 본다.
    2차부터 두 CLI를 차례로 돌려서 두 번째 대상은 03시 실행이 04시에 시작할 수 있기 때문이다.
    slot 필드가 없는 1차 기록은 실제 시작 시각이다."""
    h = r.get("slot_kst_hour")
    return h if isinstance(h, int) else r["kst_hour"]


def usable(r):
    """값(시간·토큰·점수)을 쓰는 기록인가. 기본은 성공(ok)만.
    --score-timeouts면 과제의 제한시간 도달도 쓴다 (채점은 그 시점 작업 폴더로 이미 되어 있다)."""
    if r.get("status") == "ok":
        return True
    return (SCORE_TIMEOUTS and r.get("kind") == "quality" and r.get("status") == "timeout"
            and isinstance(r.get("score"), (int, float)))


def thinking_value(r):
    """thinking 토큰. --score-timeouts에서는 실행 중 스트림으로 센 추정치(thinking_tokens_est)를 쓴다.
    제한시간에 걸린 실행은 최종 사용량 보고가 없어 thinking_tokens가 비기 때문이다(2차부터 기록)."""
    if SCORE_TIMEOUTS and isinstance(r.get("thinking_tokens_est"), (int, float)):
        return r["thinking_tokens_est"]
    return r.get("thinking_tokens")


def kst_stamp(r):
    """기록 시작 시각을 'YYYY-MM-DD HH:MM'(KST) 문자열로."""
    utc = dt.datetime.fromisoformat(r["started_utc"])
    return (utc + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")


def norm_stamp(text):
    """'2026-10-13' 또는 '2026-10-13 09:00'(KST) -> 비교용 'YYYY-MM-DD HH:MM'."""
    text = text.strip().replace("T", " ")
    return text if len(text) > 10 else text + " 00:00"


def filter_records(recs, args):
    out, dropped = [], Counter()
    since = norm_stamp(args.since) if args.since else None
    until = norm_stamp(args.until) if args.until else None
    for r in recs:
        if args.target and r.get("target") not in args.target:
            continue
        if since and kst_stamp(r) < since:
            dropped["--since 이전"] += 1
            continue
        if until and kst_stamp(r) >= until:
            dropped["--until 이후"] += 1
            continue
        if not args.all_triggers and r.get("trigger") != "schedule":
            dropped["수동/calibrate 실행"] += 1
            continue
        if not args.include_after_gap and r.get("after_gap"):
            dropped["잠자기 직후 실행"] += 1
            continue
        if not args.include_overlap and r.get("kind") == "ping" and r.get("quality_running"):
            dropped["과제 실행과 겹친 ping"] += 1
            continue
        if not args.include_extra_models:
            if r.get("extra_models"):
                dropped["요청 모델 외 다른 모델이 함께 쓰인 실행"] += 1
                continue
            broken = next((why for cli, kind, start, end, why in BROKEN_WINDOWS
                           if r.get("cli") == cli and r.get("kind") == kind
                           and start <= kst_stamp(r) < end), None)
            if broken:
                dropped[broken] += 1
                continue
        u = util_of(r)
        if u is not None and u >= args.max_util:
            dropped[f"사용량 {args.max_util:.0%} 이상"] += 1
            continue
        if getattr(args, "drop_active_pings", False) and r.get("kind") == "ping" and r.get("_account_active"):
            dropped[f"직전 기록보다 계정 사용량이 {getattr(args, 'active_delta', 0.03) * 100:g}%p 이상 오른 ping"] += 1
            continue
        out.append(r)
    return out, dropped


def mark_active_pings(recs, delta=0.03, max_gap_min=60):
    """--drop-active-pings용. 직전 기록 이후 계정의 5시간 사용량이 delta 이상 오른 ping에 _account_active=True.
    측정기 ping 하나는 5시간 사용량을 거의 움직이지 않으므로, 그만큼 오른 건 그 사이 누군가 계정을 쓴 것이다.
    - 사용량은 계정 단위라 같은 CLI의 기록끼리 시작 시각 순으로 본다. 수동·calibrate 기록도 사용량 값으로는 쓴다.
    - 기준점은 과제와 겹치지 않은 ping의 값이다. 과제 도중에 찍힌 값은 과제 사용량이 덜 반영돼 있다.
    - 기준점 이후 같은 CLI의 측정기 과제가 있었거나 기준점이 max_gap_min분보다 오래됐으면 판단하지 않는다(None, 빼지 않음).
      과제 자체가 쓰는 양과 사용자 사용을 나눌 수 없기 때문이다.
    - 5시간 창이 리셋되거나 오래된 사용이 빠지면 값이 내려가므로, 그와 겹친 사용은 못 잡는다."""
    by_cli = defaultdict(list)
    for r in recs:
        if r.get("cli") and r.get("started_utc"):
            by_cli[r["cli"]].append(r)
    for rows in by_cli.values():
        rows.sort(key=lambda r: r["started_utc"])
        anchor, task_since = None, False
        for r in rows:
            t = dt.datetime.fromisoformat(r["started_utc"])
            if r.get("kind") == "quality":
                task_since = True
                continue
            if r.get("kind") != "ping":
                continue
            u = r.get("rl_5h_util")
            has_u = isinstance(u, (int, float)) and not isinstance(u, bool)
            if anchor is None or task_since or not has_u or (t - anchor[0]).total_seconds() > max_gap_min * 60:
                r["_account_active"] = None
            else:
                r["_account_active"] = round(u - anchor[1], 4) >= delta
            if has_u and not r.get("quality_running"):
                anchor, task_since = (t, u), False


def active_report(recs, burger):
    """--drop-active-pings로 뺀 ping이 어느 시간대에 몰렸는지 (빠지는 시간대가 치우치면 비교 구성이 바뀐다)."""
    for cli in sorted({r.get("cli") for r in recs if r.get("kind") == "ping"}):
        rs = [r for r in recs if r.get("kind") == "ping" and r.get("cli") == cli]
        cnt = Counter("뺌" if r.get("_account_active") else ("판단 안 함" if r.get("_account_active") is None else "유지")
                      for r in rs)
        share = []
        for name, sel in (("버거타임", lambda r: hour_of(r) in burger), ("나머지", lambda r: hour_of(r) not in burger)):
            s = [r for r in rs if sel(r)]
            share.append(f"{name} {sum(1 for r in s if r.get('_account_active')) / max(1, len(s)):.1%}")
        print(f"  {cli} ping: 뺌 {cnt['뺌']}건 / 유지 {cnt['유지']}건 / 판단 안 함(직전 기준점이 오래됐거나 사이에 과제) "
              f"{cnt['판단 안 함']}건 / 뺀 비율 {', '.join(share)}")


# ---------------------------------------------------------------- stats

def median(xs):
    return statistics.median(xs) if xs else None


def quantile(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def cluster_of(r):
    return r.get("run_id") if r.get("kind") == "quality" else r.get("kst_date")


def clusters(recs, key, only_ok=True):
    """{묶음: [값, ...]}. key가 함수면 r -> 값(None이면 건너뜀)."""
    out = defaultdict(list)
    for r in recs:
        if only_ok and not usable(r):
            continue
        v = key(r) if callable(key) else r.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[cluster_of(r)].append(float(v))
    return list(out.values())


def _percentile_ci(draws):
    draws.sort()
    if not draws:
        return None, None
    return draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))]


def boot_mean_diff(ca, cb, rng, n_boot):
    # 묶음마다 (합, 개수)만 들고 다시 뽑으므로 기록이 많아도 빠르다.
    sa = [(sum(c), len(c)) for c in ca]
    sb = [(sum(c), len(c)) for c in cb]

    def m(cs):
        n = sum(x[1] for x in cs)
        return sum(x[0] for x in cs) / n if n else None

    point = m(sa) - m(sb)
    draws = []
    for _ in range(n_boot):
        x, y = m(rng.choices(sa, k=len(sa))), m(rng.choices(sb, k=len(sb)))
        if x is not None and y is not None:
            draws.append(x - y)
    return (point,) + _percentile_ci(draws)


def boot_median_ratio(ca, cb, rng, n_boot):
    flat = lambda cs: [v for c in cs for v in c]  # noqa: E731
    ma, mb = median(flat(ca)), median(flat(cb))
    if not ma or not mb:
        return None, None, None
    draws = []
    for _ in range(n_boot):
        x = median(flat(rng.choices(ca, k=len(ca))))
        y = median(flat(rng.choices(cb, k=len(cb))))
        if x and y:
            draws.append(x / y)
    return (ma / mb,) + _percentile_ci(draws)


def pad(text, width):
    """한글은 화면에서 두 칸을 차지하므로 표시 폭 기준으로 채운다."""
    shown = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return text + " " * max(0, width - shown)


def compare_line(label, ca, cb, kind, rng, args, scale=1.0, unit="", store=None):
    """ca=버거타임 묶음들, cb=나머지 묶음들. kind='diff'(평균 차이) 또는 'ratio'(중앙값 비율).
    store를 주면 (점추정, 구간, 묶음 수)를 RESULTS[store]에 남긴다 (--verdict용, 출력에는 영향 없음)."""
    na, nb = len(ca), len(cb)
    ra, rb = sum(map(len, ca)), sum(map(len, cb))
    sizes = f"(기록 {ra}/{rb}, 묶음 {na}/{nb})"
    if store is not None:
        RESULTS[store] = {"point": None, "lo": None, "hi": None, "na": na, "nb": nb, "ra": ra, "rb": rb}
    if na < max(1, args.min_n) or nb < max(1, args.min_n):
        return f"  {pad(label, 28)} 표본 부족 {sizes}, 묶음 최소 {args.min_n}"
    if kind == "diff":
        point, lo, hi = boot_mean_diff(ca, cb, rng, args.n_boot)
        null = 0.0
        fmt_ = lambda v: f"{v * scale:+.2f}{unit}"  # noqa: E731
    else:
        point, lo, hi = boot_median_ratio(ca, cb, rng, args.n_boot)
        null = 1.0
        fmt_ = lambda v: f"{v:.3f}x"  # noqa: E731
        if point is None:
            return f"  {pad(label, 28)} 중앙값이 0이라 비율 비교 불가 {sizes}"
    if store is not None:
        RESULTS[store].update(point=point, lo=lo, hi=hi)
    if lo is None:
        return f"  {pad(label, 28)} {fmt_(point)}  (신뢰구간 계산 불가) {sizes}"
    sig = "  <- 유의" if (lo > null or hi < null) else ""
    return f"  {pad(label, 28)} {fmt_(point)}  [{fmt_(lo)} ~ {fmt_(hi)}]  {sizes}{sig}"


# ---------------------------------------------------------------- report pieces

def values(recs, key, only_ok=True):
    return [v for c in clusters(recs, key, only_ok) for v in c]


def fmt(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def server_error_flag(r):
    """서버 쪽 실패면 1, 성공이면 0. 한도 초과·측정기 오류는 None(분모에서 제외)."""
    if r.get("status") == "ok":
        return 0.0
    if usable(r):  # --score-timeouts: 과제 제한시간 도달은 작업 시간 예산이 끝난 것이지 서버 오류가 아니다
        return 0.0
    if r.get("status") in SERVER_ERRORS:
        return 1.0
    return None


def hourly_table(recs, kind, burger):
    by_hour = defaultdict(list)
    for r in recs:
        by_hour[hour_of(r)].append(r)
    if kind == "ping":
        print("   시    n  서버오류  한도   첫응답p50   p90  TTFT ms p50  전체p50")
    else:
        print("   시    n  서버오류  한도   점수평균  thinking p50  도구호출 p50  소요(초) p50")
    for h in range(24):
        rs = by_hour.get(h, [])
        if not rs:
            continue
        mark = "*" if h in burger else " "
        flags = [f for f in map(server_error_flag, rs) if f is not None]
        err = f"{mean(flags):4.0%}" if flags else "   -"
        limited = sum(r.get("status") == "rate_limited" for r in rs)
        if kind == "ping":
            first = values(rs, "t_first_output_sec")
            print(f"  {mark}{h:02d}  {len(rs):4d}    {err}  {limited:4d}   {fmt(median(first), 2):>8}  "
                  f"{fmt(quantile(first, 0.9), 2):>5}   {fmt(median(values(rs, 'ttft_ms')), 0):>10}  "
                  f"{fmt(median(values(rs, 'wall_sec')), 2):>7}")
        else:
            print(f"  {mark}{h:02d}  {len(rs):4d}    {err}  {limited:4d}   {fmt(mean(values(rs, 'score')), 3):>7}  "
                  f"{fmt(median(values(rs, thinking_value)), 0):>12}  "
                  f"{fmt(median(values(rs, 'tool_calls')), 0):>12}  "
                  f"{fmt(median(values(rs, 'wall_sec')), 0):>12}")


def centered_scores(recs):
    """과제마다 난이도가 다르므로 과제 평균을 빼서 비교한다."""
    by_task = defaultdict(list)
    for r in recs:
        if usable(r) and isinstance(r.get("score"), (int, float)):
            by_task[r.get("task")].append(r["score"])
    task_mean = {t: mean(v) for t, v in by_task.items()}
    for r in recs:
        if usable(r) and isinstance(r.get("score"), (int, float)):
            r["_centered"] = r["score"] - task_mean[r.get("task")]
        else:
            r["_centered"] = None


def has_field(recs, key):
    return any(isinstance(r.get(key), (int, float)) for r in recs)


def comparison(recs, kind, burger, rng, args, title, tag=None):
    """tag=(대상 이름, 부분집합 이름)을 주면 각 줄의 결과를 RESULTS에 남긴다 (출력은 같다)."""
    def key(label):
        return None if tag is None else tag + (kind, label)

    a = [r for r in recs if hour_of(r) in burger]
    b = [r for r in recs if hour_of(r) not in burger]
    print(f"  -- {title}: 버거타임 {len(a)}건 vs 나머지 {len(b)}건")
    print(compare_line("서버 오류율 차이", clusters(a, server_error_flag, False),
                       clusters(b, server_error_flag, False), "diff", rng, args, 100, "%p",
                       store=key("서버 오류율 차이")))
    la = sum(r.get("status") == "rate_limited" for r in a)
    lb = sum(r.get("status") == "rate_limited" for r in b)
    if la or lb:
        print(f"  {pad('사용량 한도 걸림', 28)} 버거 {la}건 / 나머지 {lb}건"
              " (내 사용 패턴 영향이라 판단에서 제외)")
    if kind == "ping":
        print(compare_line("첫 응답 시간 (중앙값 비)", clusters(a, "t_first_output_sec"),
                           clusters(b, "t_first_output_sec"), "ratio", rng, args,
                           store=key("첫 응답 시간 (중앙값 비)")))
        ttft_a, ttft_b = clusters(a, "ttft_ms"), clusters(b, "ttft_ms")
        if ttft_a or ttft_b:
            print(compare_line("API TTFT (중앙값 비)", ttft_a, ttft_b, "ratio", rng, args,
                               store=key("API TTFT (중앙값 비)")))
        print(compare_line("전체 소요 (중앙값 비)", clusters(a, "wall_sec"), clusters(b, "wall_sec"),
                           "ratio", rng, args))
        # 2차부터 기록하는 단계별 시간. 1차 기록에는 없어서 이 줄들은 나오지 않는다.
        for field, label in (("t_model_sec", "모델 응답 시간 (중앙값 비)"),
                             ("t_prep_sec", "CLI 준비 시간 (중앙값 비)"),
                             ("net_ttfb_ms", "통신 시간 (중앙값 비)")):
            if has_field(recs, field):
                print(compare_line(label, clusters(a, field), clusters(b, field), "ratio", rng, args,
                                   store=key(label)))
    else:
        if SCORE_TIMEOUTS:
            timed = lambda r: 1.0 if r.get("status") == "timeout" else 0.0  # noqa: E731
            print(compare_line("제한시간 도달 비율 차이", clusters(a, timed), clusters(b, timed),
                               "diff", rng, args, 100, "%p", store=key("제한시간 도달 비율 차이")))
        print(compare_line("점수 차이 (과제 보정)", clusters(a, "_centered"), clusters(b, "_centered"),
                           "diff", rng, args, 100, "%p", store=key("점수 차이 (과제 보정)")))
        print(compare_line("thinking 토큰 (중앙값 비)", clusters(a, thinking_value),
                           clusters(b, thinking_value), "ratio", rng, args,
                           store=key("thinking 토큰 (중앙값 비)")))
        print(compare_line("도구 호출 수 (중앙값 비)", clusters(a, "tool_calls"),
                           clusters(b, "tool_calls"), "ratio", rng, args))
        print(compare_line("출력 토큰 (중앙값 비)", clusters(a, "output_tokens"),
                           clusters(b, "output_tokens"), "ratio", rng, args))
        print(compare_line("소요 시간 (중앙값 비)", clusters(a, "wall_sec"), clusters(b, "wall_sec"),
                           "ratio", rng, args, store=key("소요 시간 (중앙값 비)")))


def target_report(name, recs, args, burger, rng):
    cli = recs[0].get("cli")
    print(f"\n{'=' * 78}\n{name}  ({cli})\n{'=' * 78}")

    versions = defaultdict(list)
    for r in recs:
        versions[r.get("cli_version")].append(r.get("kst_date"))
    print("CLI 버전:")
    for v, dates in sorted(versions.items(), key=lambda kv: min(d or "" for d in kv[1])):
        dates = [d for d in dates if d]
        span = f"{min(dates)} ~ {max(dates)}" if dates else "-"
        print(f"  {v}: {span} ({len(dates)}건)")
    if len(versions) > 1:
        print("  * 버전이 여러 개입니다. 업데이트 전후 차이가 섞이지 않게 --since 로 나눠 보세요.")

    served = Counter(r.get("served_model") for r in recs if r.get("served_model"))
    efforts = Counter(r.get("served_effort") for r in recs if r.get("served_effort"))
    mismatches = [r for r in recs if r.get("model_mismatch")]
    print(f"실제 모델: {dict(served)}" + (f"  effort: {dict(efforts)}" if efforts else ""))
    print(f"요청과 다른 모델이 돈 기록: {len(mismatches)}건")
    for r in mismatches[:5]:
        print(f"  {r.get('started_utc')} {r.get('kind')} 요청={r.get('requested_model')} "
              f"실제={r.get('served_models')}")

    status = Counter(r.get("status") for r in recs)
    print("상태:", ", ".join(f"{k} {v}" for k, v in status.most_common()))
    if status.get("auth_error"):
        print(f"인증 오류 {status['auth_error']}건 - 토큰(.env의 CLAUDE_CODE_OAUTH_TOKEN)이나 로그인을 확인하세요."
              " 서버 오류율에는 넣지 않습니다.")
    untouched = [r for r in recs if r.get("kind") == "quality" and r.get("status") == "ok"
                 and r.get("workspace_changed") is False]
    if untouched:
        hours = Counter(r["kst_hour"] for r in untouched)
        print(f"파일을 하나도 안 고친 과제 실행: {len(untouched)}건 (한국시각별 {dict(sorted(hours.items()))})"
              " - 권한·샌드박스 문제인지 raw 로그 확인 필요")
    if cli == "codex" and any(r.get("kind") == "quality" for r in recs):
        print("참고: " + CODEX_THINKING_NOTE)
    hashes = Counter(r.get("prompt_hash") for r in recs if r.get("kind") == "ping" and r.get("prompt_hash"))
    if hashes:  # 2차부터 기록. 요청 구성(시스템 지시·스킬 목록)이 기간 중에 바뀌었는지 보여 준다.
        print(f"ping 요청 구성(prompt_hash) {len(hashes)}종: {dict(hashes.most_common(5))}")
    drift = sum(1 for r in recs if r.get("version_drift"))
    if drift:
        print(f"고정한 CLI 버전과 다른 버전으로 돈 기록: {drift}건 (version_drift)")

    for kind in ("ping", "quality"):
        rs = [r for r in recs if r.get("kind") == kind]
        if not rs:
            continue
        if kind == "quality":
            centered_scores(rs)
        unit = "날짜" if kind == "ping" else "과제 실행(run)"
        label = "응답 속도 (ping)" if kind == "ping" else "코딩 과제 (quality)"
        print(f"\n[{label}]  한국시간별  (* = 버거타임, 신뢰구간 묶음 단위 = {unit})")
        hourly_table(rs, kind, burger)
        print()
        comparison(rs, kind, burger, rng, args, "전체 요일", tag=(name, "all"))
        weekday = [r for r in rs if r.get("us_pacific_weekday") is not None and r["us_pacific_weekday"] < 5]
        comparison(weekday, kind, burger, rng, args, "미국 평일만 (태평양시 월~금)", tag=(name, "weekday"))
        if kind == "quality":
            print("\n  과제별 점수 평균 (버거타임 / 나머지)")
            by_task = defaultdict(lambda: ([], []))
            for r in rs:
                if usable(r) and isinstance(r.get("score"), (int, float)):
                    by_task[r.get("task")][0 if hour_of(r) in burger else 1].append(r["score"])
            for task, (sa, sb) in sorted(by_task.items()):
                print(f"    {task:<16} {fmt(mean(sa), 3)} (n={len(sa)}) / {fmt(mean(sb), 3)} (n={len(sb)})")


# ---------------------------------------------------------------- verdict (--verdict)

def _metric_fn(key):
    """판정 지표 값 -> (clusters()에 줄 key, 성공 기록만 쓰는지)."""
    if key == "_server_error":
        return server_error_flag, False
    if key == "_thinking":
        return thinking_value, True
    return key, True


def _split_clusters(recs, burger, key):
    fn, only_ok = _metric_fn(key)
    a = [r for r in recs if hour_of(r) in burger]
    b = [r for r in recs if hour_of(r) not in burger]
    return clusters(a, fn, only_ok), clusters(b, fn, only_ok)


def _point(ca, cb, how):
    fa = [v for c in ca for v in c]
    fb = [v for c in cb for v in c]
    if not fa or not fb:
        return None
    if how == "ratio":
        ma, mb = median(fa), median(fb)
        return ma / mb if ma and mb else None
    return mean(fa) - mean(fb)


def _boot_p(ca, cb, how, rng, n_boot):
    """양쪽 묶음을 따로 다시 뽑는 기존 방식으로 양측 부트스트랩 p값 근사. 등록 규칙에는 없는 참고값."""
    null = 1.0 if how == "ratio" else 0.0
    draws = []
    for _ in range(n_boot):
        x = _point(rng.choices(ca, k=len(ca)), rng.choices(cb, k=len(cb)), how)
        if x is not None:
            draws.append(x)
    if not draws:
        return None
    below = sum(d <= null for d in draws) / len(draws)
    above = sum(d >= null for d in draws) / len(draws)
    return max(1.0 / len(draws), min(1.0, 2 * min(below, above)))


def _interaction(recs, burger, key, how, rng, n_boot):
    """미국 평일의 버거타임 효과 ÷ 주말의 버거타임 효과 (diff는 평일 차이 − 주말 차이).
    날짜를 통째로 다시 뽑아 네 칸(평일·주말 × 버거·나머지)이 같은 날짜 표본에서 나오게 한다."""
    fn, only_ok = _metric_fn(key)
    days = defaultdict(lambda: ([], [], [], []))
    for r in recs:
        if only_ok and not usable(r):
            continue
        v = fn(r) if callable(fn) else r.get(fn)
        wd = r.get("us_pacific_weekday")
        if wd is None or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        days[r["kst_date"]][(0 if wd < 5 else 2) + (0 if hour_of(r) in burger else 1)].append(float(v))
    keys = list(days)
    n_days = [sum(1 for d in keys if days[d][i]) for i in range(4)]

    def stat(sample):
        cells = [[v for d in sample for v in days[d][i]] for i in range(4)]
        if any(not c for c in cells):
            return None
        if how == "ratio":
            m = [median(c) for c in cells]
            return (m[0] / m[1]) / (m[2] / m[3]) if all(m) else None
        return (mean(cells[0]) - mean(cells[1])) - (mean(cells[2]) - mean(cells[3]))

    point = stat(keys) if keys else None
    if point is None or min(n_days) < 3:
        return point, None, None, n_days
    draws = [x for x in (stat([rng.choice(keys) for _ in keys]) for _ in range(n_boot)) if x is not None]
    lo, hi = _percentile_ci(draws)
    return point, lo, hi, n_days


def _holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    adj, running = [None] * len(pvals), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvals) - rank) * pvals[i]))
        adj[i] = running
    return adj


def verdict(by_target, args, burger):
    """사전 등록 규칙 1~4로 판정표를 만든다. 전체 구간의 점추정·신뢰구간과 미국 평일 점추정은 위 비교 줄의 값을
    그대로 쓰고(RESULTS), 전반·후반은 구간을 반으로 나눠 점추정만 다시 계산한다(난수 없음).
    평일÷주말 상호작용, p값, Holm 보정은 등록 규칙 밖의 참고값이며 별도 난수(seed+1)로 계산한다."""
    if not (args.since and args.until):
        print("\n--verdict에는 --since와 --until이 필요합니다 (판정 구간과 전반·후반 경계를 정하려고).")
        return
    t0 = dt.datetime.strptime(norm_stamp(args.since), "%Y-%m-%d %H:%M")
    t1 = dt.datetime.strptime(norm_stamp(args.until), "%Y-%m-%d %H:%M")
    mid = (t0 + (t1 - t0) / 2).strftime("%Y-%m-%d %H:%M")
    rng = random.Random(args.seed + 1)
    rows = []
    for cli, kind, label, key, how, (blo, bhi) in VERDICT_SETS[args.verdict]:
        for name in sorted(n for n, rs in by_target.items() if rs and rs[0].get("cli") == cli):
            rs = [r for r in by_target[name] if r.get("kind") == kind]
            res = RESULTS.get((name, "all", kind, label)) or {}
            point, lo, hi = res.get("point"), res.get("lo"), res.get("hi")
            wd = (RESULTS.get((name, "weekday", kind, label)) or {}).get("point")
            halves = []
            for part in ([r for r in rs if kst_stamp(r) < mid], [r for r in rs if kst_stamp(r) >= mid]):
                ca, cb = _split_clusters(part, burger, key)
                enough = len(ca) >= max(1, args.min_n) and len(cb) >= max(1, args.min_n)
                halves.append(_point(ca, cb, how) if enough else None)
            null = 1.0 if how == "ratio" else 0.0

            def same(x):
                return x is not None and point is not None and (x - null) * (point - null) > 0

            r1 = lo is not None and hi is not None and (lo > null or hi < null)
            r2 = point is not None and (point >= bhi or point <= blo)
            r3, r4 = same(wd), same(halves[0]) and same(halves[1])
            if r1 and r2 and r3 and r4:
                v = "효과 있음 (버거타임 쪽이 " + ("작음" if point < null else "큼") + ")"
            elif r1 and r2:
                v = "약한 신호"
            elif lo is not None and hi is not None and blo <= lo and hi <= bhi:
                v = "차이 없음"
            else:
                v = "판단 불가" + (" (표본 부족)" if point is None else "")
            ca, cb = _split_clusters(rs, burger, key)
            events = None
            if key == "_server_error":
                events = int(sum(v_ for c in ca + cb for v_ in c))
            p = _boot_p(ca, cb, how, rng, args.n_boot) if ca and cb else None
            inter = _interaction(rs, burger, key, how, rng, args.n_boot)
            rows.append({"name": name, "label": label, "how": how, "point": point, "lo": lo, "hi": hi,
                         "wd": wd, "h1": halves[0], "h2": halves[1], "rules": (r1, r2, r3, r4),
                         "verdict": v, "p": p, "inter": inter, "events": events, "bounds": (blo, bhi)})

    ps = [r["p"] for r in rows if r["p"] is not None]
    adj = iter(_holm(ps)) if ps else iter(())
    for r in rows:
        r["p_holm"] = next(adj) if r["p"] is not None else None

    def f(x, how):
        if x is None:
            return "-"
        return f"{x:.3f}x" if how == "ratio" else f"{x * 100:+.2f}%p"

    print(f"\n{'=' * 78}\n판정 (사전 등록 규칙, 지표 세트 {args.verdict})\n{'=' * 78}")
    print(f"구간 {norm_stamp(args.since)} ~ {norm_stamp(args.until)}, 전반·후반 경계 {mid}")
    for r in rows:
        ok = " ".join(f"{i + 1}{'O' if x else 'X'}" for i, x in enumerate(r["rules"]))
        blo, bhi = r["bounds"]
        print(f"\n  {r['name']} / {r['label']}   최소 크기 {f(blo, r['how'])} ~ {f(bhi, r['how'])}")
        print(f"    전체 {f(r['point'], r['how'])} [{f(r['lo'], r['how'])} ~ {f(r['hi'], r['how'])}]"
              f"  미국평일 {f(r['wd'], r['how'])}  전반 {f(r['h1'], r['how'])}  후반 {f(r['h2'], r['how'])}")
        note = f"  (서버 오류 {r['events']}건)" if r["events"] is not None else ""
        print(f"    규칙 {ok}  ->  {r['verdict']}{note}")
        ip, ilo, ihi, nd = r["inter"]
        unit = "÷" if r["how"] == "ratio" else "−"
        pval = "-" if r["p"] is None else f"{r['p']:.3f}"
        holm = "-" if r["p_holm"] is None else f"{r['p_holm']:.3f}"
        print(f"    참고: 평일효과{unit}주말효과 {f(ip, r['how'])} [{f(ilo, r['how'])} ~ {f(ihi, r['how'])}]"
              f" (날짜 수 평일버거/평일나머지/주말버거/주말나머지 {'/'.join(map(str, nd))})"
              f"  p {pval}  Holm p {holm}")
    print("\n판정 이름: 효과 있음 = 규칙 1~4 모두 충족 / 약한 신호 = 1·2만 충족 /"
          "\n  차이 없음 = 1·2를 충족하지 못했고 신뢰구간 전체가 최소 크기 범위 안 /"
          "\n  판단 불가 = 1·2를 충족하지 못했고 신뢰구간이 최소 크기 밖까지 걸침 (있을 수도 없을 수도 있음)")
    print("규칙: 1 전체 신뢰구간이 기준선(1.00x 또는 0%p)을 포함하지 않음, 2 점추정이 최소 크기 이상,"
          "\n  3 미국 평일 점추정이 같은 방향, 4 전반·후반 점추정이 모두 같은 방향(표본 부족이면 불충족)")
    print("참고 값(등록 규칙 밖): 평일효과÷주말효과 = (미국 평일의 버거÷나머지) ÷ (주말의 버거÷나머지)."
          "\n  1보다 작으면(차이는 0보다 작으면) 미국 평일에 버거타임 쪽이 상대적으로 더 작다(빠르다·적다)."
          "\n  '미국 업무시간 부하 때문'이라면 평일에 버거타임 쪽이 더 커야(1보다 커야) 한다."
          "\n  p와 Holm p는 기존 방식 부트스트랩 근사이고, Holm은 이 표의 지표 전체에 대한 보정이다.")
    print("서버 오류율은 CLI가 내부에서 재시도하고도 끝내 실패한 실행만 셉니다. 재시도로 복구된 장애는 지연으로만 남습니다.")


def apply_regrade(recs, path):
    """run_bench.py regrade 결과(다시 채점한 점수들)의 중앙값으로 과제 점수를 바꾼다."""
    table = {}
    for row in load(path):
        if isinstance(row.get("median"), (int, float)):
            table[(row.get("run_id"), row.get("target"), row.get("task"))] = row
    replaced = missing = mismatched = 0
    for r in recs:
        if r.get("kind") != "quality" or not isinstance(r.get("score"), (int, float)):
            continue
        row = table.get((r.get("run_id"), r.get("target"), r.get("task")))
        if row is None:
            missing += 1
        elif row.get("task_version") != r.get("task_version"):
            mismatched += 1
        else:
            r["score_live"], r["score"] = r["score"], row["median"]
            replaced += 1
    print(f"다시 채점한 점수로 바꾼 과제 기록 {replaced}건 / 다시 채점 기록 없음 {missing}건"
          f" / 과제 버전이 달라 안 바꿈 {mismatched}건 (없거나 다른 건 실시간 채점 점수 그대로)")


CSV_COLUMNS = [
    "started_utc", "kst_date", "kst_hour", "us_pacific_weekday", "kind", "trigger", "run_id", "target",
    "cli", "task", "task_version", "status", "score", "passed", "total", "requested_model",
    "served_model", "model_mismatch", "extra_models", "advisor_calls", "requested_effort", "served_effort", "cli_version",
    "t_first_output_sec", "ttft_ms", "duration_api_ms", "wall_sec", "num_turns", "tool_calls",
    "output_tokens", "thinking_tokens", "input_tokens", "cached_input_tokens", "rl_5h_util",
    "rl_7d_util", "inference_geo", "service_tier", "after_gap", "quality_running",
    "workspace_changed", "permission_denials", "error",
    # 2차부터
    "started_ts", "slot_kst_hour", "cli_order", "t_boot_sec", "t_prep_sec", "t_model_sec",
    "net_host", "net_dns_ms", "net_tcp_ms", "net_tls_ms", "net_ttfb_ms", "net_status", "net_error",
    "prompt_hash", "remote_plugins", "version_drift", "thinking_tokens_est", "grade_wall_sec", "load_avg_1m",
    "score_live",
]


def main():
    ap = argparse.ArgumentParser(description="버거타임 분석")
    ap.add_argument("--file", default=str(BENCH_DIR / "results" / "runs.jsonl"))
    ap.add_argument("--burger", default="1-6", help="버거타임으로 볼 한국시간 (기본 1-6 = 01:00~06:59)")
    ap.add_argument("--since", help="이 시각(KST, 'YYYY-MM-DD' 또는 'YYYY-MM-DD HH:MM') 이후 기록만")
    ap.add_argument("--until", help="이 시각(KST) 전 기록만 (그 시각은 제외)")
    ap.add_argument("--target", action="append", help="특정 대상만 (여러 번 지정 가능)")
    ap.add_argument("--max-util", type=float, default=0.95,
                    help="사용량 한도 사용률이 이 값 이상인 기록 제외 (기본 0.95)")
    ap.add_argument("--include-after-gap", action="store_true", help="잠자기 직후 실행도 포함")
    ap.add_argument("--include-overlap", action="store_true", help="과제 실행과 겹친 ping도 포함")
    ap.add_argument("--include-extra-models", action="store_true",
                    help="다른 모델(advisor 등)이 함께 쓰인 실행과 BROKEN_WINDOWS 구간도 포함")
    ap.add_argument("--all-triggers", action="store_true", help="수동·calibrate 실행도 포함")
    ap.add_argument("--min-n", type=int, default=10,
                    help="비교에 필요한 최소 묶음 수 (ping=날짜 수, quality=실행 수)")
    ap.add_argument("--n-boot", type=int, default=1000, help="부트스트랩 반복 횟수")
    ap.add_argument("--csv", help="걸러진 기록을 CSV로 저장")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verdict", choices=sorted(VERDICT_SETS),
                    help="사전 등록 규칙으로 판정표 출력 (--since/--until 필요, 기존 출력 뒤에 붙음)")
    ap.add_argument("--score-timeouts", action="store_true",
                    help="과제 제한시간에 걸린 실행도 그 시점 점수·시간·thinking 추정치로 포함 (기본: 성공만)")
    ap.add_argument("--regrade", help="run_bench.py regrade 결과 파일. 과제 점수를 다시 채점한 중앙값으로 바꿈")
    ap.add_argument("--drop-active-pings", action="store_true",
                    help="민감도 분석: 직전 기록보다 계정 5시간 사용량이 --active-delta 이상 오른 ping을 뺌 (2차 기준)")
    ap.add_argument("--active-delta", type=float, default=0.03,
                    help="--drop-active-pings의 기준 (5시간 사용량 증가분, 기본 0.03 = 3%%p)")
    args = ap.parse_args()
    global SCORE_TIMEOUTS
    SCORE_TIMEOUTS = args.score_timeouts

    path = Path(args.file)
    if not path.exists():
        print(f"{path} 가 없습니다. 먼저 run_bench.py 로 기록을 쌓으세요.")
        return 1
    burger = parse_hours(args.burger)
    loaded = load(path)
    if args.drop_active_pings:
        mark_active_pings(loaded, args.active_delta)
    recs, dropped = filter_records(loaded, args)
    print(f"기록 {len(recs)}건 사용" + (f" / 제외: {dict(dropped)}" if dropped else ""))
    print(f"버거타임 = 한국시간 {sorted(burger)}시")
    if args.drop_active_pings:
        print(f"민감도 분석: 직전 기록보다 계정 5시간 사용량이 {args.active_delta * 100:g}%p 이상 오른 ping을 뺌"
              " (--drop-active-pings, 다른 제외 규칙을 통과한 ping 기준)")
        active_report(filter_records(loaded, argparse.Namespace(**{**vars(args), "drop_active_pings": False}))[0],
                      burger)
    if args.score_timeouts:
        print("과제: 제한시간에 걸린 실행도 그 시점 산출물 점수로 포함 (--score-timeouts)")
    if args.regrade:
        apply_regrade(recs, args.regrade)
    rng = random.Random(args.seed)

    by_target = defaultdict(list)
    for r in recs:
        by_target[r.get("target")].append(r)
    for name in sorted(by_target):
        target_report(name, by_target[name], args, burger, rng)
    if args.verdict:
        verdict(by_target, args, burger)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in recs:
                w.writerow({k: r.get(k) for k in CSV_COLUMNS})
        print(f"\nCSV 저장: {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
