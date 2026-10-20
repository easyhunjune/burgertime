#!/usr/bin/env python3
"""버거타임 분석: results/runs.jsonl 을 한국 시간대별로 묶고, 버거타임과 나머지 시간을 비교한다.

  python3 analyze.py                      # 기본: 한국시간 01~06시를 버거타임으로
  python3 analyze.py --burger 0-5         # 구간 바꾸기 (22-3처럼 자정을 넘겨도 됨)
  python3 analyze.py --since 2026-10-20   # 특정 날짜 이후만 (CLI 업데이트 이후만 보고 싶을 때)
  python3 analyze.py --since "2026-10-13 09:00" --until "2026-11-10 09:00"   # 시각(KST) 단위 구간
  python3 analyze.py --csv out.csv        # 걸러진 기록을 CSV로 내보내기

신뢰구간은 클러스터 부트스트랩으로 구한다. 한 번의 과제 실행(run_id)에서 나온 기록들, 같은 날의 ping들은
서로 묶여 움직이므로 기록 하나하나를 독립 표본으로 치면 구간이 실제보다 좁아진다.
그래서 quality는 실행 단위, ping은 날짜 단위로 통째로 다시 뽑는다. 최소 표본 수(--min-n)도 이 묶음 수 기준이다.
구간이 0(차이) 또는 1.00x(비율)을 포함하지 않으면 '유의'로 표시한다.
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
        out.append(r)
    return out, dropped


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
        if only_ok and r.get("status") != "ok":
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


def compare_line(label, ca, cb, kind, rng, args, scale=1.0, unit=""):
    """ca=버거타임 묶음들, cb=나머지 묶음들. kind='diff'(평균 차이) 또는 'ratio'(중앙값 비율)."""
    na, nb = len(ca), len(cb)
    ra, rb = sum(map(len, ca)), sum(map(len, cb))
    sizes = f"(기록 {ra}/{rb}, 묶음 {na}/{nb})"
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
    if r.get("status") in SERVER_ERRORS:
        return 1.0
    return None


def hourly_table(recs, kind, burger):
    by_hour = defaultdict(list)
    for r in recs:
        by_hour[r["kst_hour"]].append(r)
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
                  f"{fmt(median(values(rs, 'thinking_tokens')), 0):>12}  "
                  f"{fmt(median(values(rs, 'tool_calls')), 0):>12}  "
                  f"{fmt(median(values(rs, 'wall_sec')), 0):>12}")


def centered_scores(recs):
    """과제마다 난이도가 다르므로 과제 평균을 빼서 비교한다."""
    by_task = defaultdict(list)
    for r in recs:
        if r.get("status") == "ok" and isinstance(r.get("score"), (int, float)):
            by_task[r.get("task")].append(r["score"])
    task_mean = {t: mean(v) for t, v in by_task.items()}
    for r in recs:
        if r.get("status") == "ok" and isinstance(r.get("score"), (int, float)):
            r["_centered"] = r["score"] - task_mean[r.get("task")]
        else:
            r["_centered"] = None


def comparison(recs, kind, burger, rng, args, title):
    a = [r for r in recs if r["kst_hour"] in burger]
    b = [r for r in recs if r["kst_hour"] not in burger]
    print(f"  -- {title}: 버거타임 {len(a)}건 vs 나머지 {len(b)}건")
    print(compare_line("서버 오류율 차이", clusters(a, server_error_flag, False),
                       clusters(b, server_error_flag, False), "diff", rng, args, 100, "%p"))
    la = sum(r.get("status") == "rate_limited" for r in a)
    lb = sum(r.get("status") == "rate_limited" for r in b)
    if la or lb:
        print(f"  {pad('사용량 한도 걸림', 28)} 버거 {la}건 / 나머지 {lb}건"
              " (내 사용 패턴 영향이라 판단에서 제외)")
    if kind == "ping":
        print(compare_line("첫 응답 시간 (중앙값 비)", clusters(a, "t_first_output_sec"),
                           clusters(b, "t_first_output_sec"), "ratio", rng, args))
        ttft_a, ttft_b = clusters(a, "ttft_ms"), clusters(b, "ttft_ms")
        if ttft_a or ttft_b:
            print(compare_line("API TTFT (중앙값 비)", ttft_a, ttft_b, "ratio", rng, args))
        print(compare_line("전체 소요 (중앙값 비)", clusters(a, "wall_sec"), clusters(b, "wall_sec"),
                           "ratio", rng, args))
    else:
        print(compare_line("점수 차이 (과제 보정)", clusters(a, "_centered"), clusters(b, "_centered"),
                           "diff", rng, args, 100, "%p"))
        print(compare_line("thinking 토큰 (중앙값 비)", clusters(a, "thinking_tokens"),
                           clusters(b, "thinking_tokens"), "ratio", rng, args))
        print(compare_line("도구 호출 수 (중앙값 비)", clusters(a, "tool_calls"),
                           clusters(b, "tool_calls"), "ratio", rng, args))
        print(compare_line("출력 토큰 (중앙값 비)", clusters(a, "output_tokens"),
                           clusters(b, "output_tokens"), "ratio", rng, args))
        print(compare_line("소요 시간 (중앙값 비)", clusters(a, "wall_sec"), clusters(b, "wall_sec"),
                           "ratio", rng, args))


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
        comparison(rs, kind, burger, rng, args, "전체 요일")
        weekday = [r for r in rs if r.get("us_pacific_weekday") is not None and r["us_pacific_weekday"] < 5]
        comparison(weekday, kind, burger, rng, args, "미국 평일만 (태평양시 월~금)")
        if kind == "quality":
            print("\n  과제별 점수 평균 (버거타임 / 나머지)")
            by_task = defaultdict(lambda: ([], []))
            for r in rs:
                if r.get("status") == "ok" and isinstance(r.get("score"), (int, float)):
                    by_task[r.get("task")][0 if r["kst_hour"] in burger else 1].append(r["score"])
            for task, (sa, sb) in sorted(by_task.items()):
                print(f"    {task:<16} {fmt(mean(sa), 3)} (n={len(sa)}) / {fmt(mean(sb), 3)} (n={len(sb)})")


CSV_COLUMNS = [
    "started_utc", "kst_date", "kst_hour", "us_pacific_weekday", "kind", "trigger", "run_id", "target",
    "cli", "task", "task_version", "status", "score", "passed", "total", "requested_model",
    "served_model", "model_mismatch", "extra_models", "advisor_calls", "requested_effort", "served_effort", "cli_version",
    "t_first_output_sec", "ttft_ms", "duration_api_ms", "wall_sec", "num_turns", "tool_calls",
    "output_tokens", "thinking_tokens", "input_tokens", "cached_input_tokens", "rl_5h_util",
    "rl_7d_util", "inference_geo", "service_tier", "after_gap", "quality_running",
    "workspace_changed", "permission_denials", "error",
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
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"{path} 가 없습니다. 먼저 run_bench.py 로 기록을 쌓으세요.")
        return 1
    burger = parse_hours(args.burger)
    recs, dropped = filter_records(load(path), args)
    print(f"기록 {len(recs)}건 사용" + (f" / 제외: {dict(dropped)}" if dropped else ""))
    print(f"버거타임 = 한국시간 {sorted(burger)}시")
    rng = random.Random(args.seed)

    by_target = defaultdict(list)
    for r in recs:
        by_target[r.get("target")].append(r)
    for name in sorted(by_target):
        target_report(name, by_target[name], args, burger, rng)

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
