#!/usr/bin/env python3
"""1차 사후 분석 (2026-11-21, 판정과 별개): 핑의 첫 응답 시간을 단계별로 나눠 본다.

    python3 data/round1/phase_check.py

- 기록 선택은 판정과 똑같다: analyze.py의 제외 규칙(기본값)과 분석 구간 2026-10-13 09:00 ~ 11-10 09:00 KST.
- Codex: codex_ping_phases.jsonl(측정용 맥의 Codex 세션 로그에서 뽑은 단계별 시각)을 run_id로 붙인다.
    t_prep_sec  세션 생성 ~ 프롬프트 기록 (지시문·스킬·플러그인 구성, 원격 동기화 포함)
    t_model_sec 프롬프트 기록 ~ 답 기록 (요청 전송·서버 대기·추론·출력)
- Claude: runs.jsonl의 ttft_ms(CLI가 잰 첫 토큰 시간)와, 첫 응답 시간에서 그것을 뺀 나머지(CLI 쪽 시간).
- 신뢰구간은 날짜를 통째로 다시 뽑는 방식(같은 날의 버거타임·나머지를 함께)으로 1000번, seed 42.
  판정표(analyze.py)는 두 쪽을 따로 다시 뽑으므로 방식이 다르다. 점추정은 같은 식(중앙값 비)이다.
"""
import json
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
import analyze  # noqa: E402

BURGER = set(range(1, 7))
ARGS = SimpleNamespace(target=None, since="2026-10-13 09:00", until="2026-11-10 09:00", all_triggers=False,
                       include_after_gap=False, include_overlap=False, include_extra_models=False, max_util=0.95)


def ratio_ci(rows, key, rng, n_boot=1000):
    days = defaultdict(lambda: ([], []))
    for r in rows:
        v = key(r)
        if isinstance(v, (int, float)):
            days[r["kst_date"]][0 if r["kst_hour"] in BURGER else 1].append(v)
    keys = sorted(days)

    def stat(sample):
        a = [v for d in sample for v in days[d][0]]
        b = [v for d in sample for v in days[d][1]]
        return st.median(a) / st.median(b) if a and b else None

    point = stat(keys)
    draws = sorted(x for x in (stat([rng.choice(keys) for _ in keys]) for _ in range(n_boot)) if x)
    na = sum(1 for r in rows if r["kst_hour"] in BURGER and isinstance(key(r), (int, float)))
    nb = sum(1 for r in rows if r["kst_hour"] not in BURGER and isinstance(key(r), (int, float)))
    return point, draws[int(0.025 * (len(draws) - 1))], draws[int(0.975 * (len(draws) - 1))], na, nb


def line(label, res):
    p, lo, hi, na, nb = res
    return f"  {label:<34} {p:.3f}x [{lo:.3f} ~ {hi:.3f}]  (기록 {na}/{nb})"


def main():
    recs, _ = analyze.filter_records(analyze.load(HERE / "runs.jsonl"), ARGS)
    pings = [r for r in recs if r.get("kind") == "ping" and r.get("status") == "ok"]
    phases = {(p["run_id"], p["target"]): p for p in analyze.load(HERE / "codex_ping_phases.jsonl")}
    rng = random.Random(42)

    cx = [dict(r, **phases.get((r["run_id"], r["target"]), {})) for r in pings if r.get("cli") == "codex"]
    with_phase = [r for r in cx if isinstance(r.get("t_model_sec"), (int, float))]
    print(f"Codex 핑 (판정과 같은 기록): {len(cx)}건, 단계별 시각이 있는 것 {len(with_phase)}건")
    print("\n  KST시   첫응답  CLI준비  모델응답   (중앙값, 초, * = 버거타임)")
    for h in range(24):
        s = [r for r in with_phase if r["kst_hour"] == h]
        if s:
            print(f"  {'*' if h in BURGER else ' '}{h:02d}    {st.median(r['t_first_output_sec'] for r in s):6.2f}"
                  f"  {st.median(r['t_prep_sec'] for r in s):6.2f}  {st.median(r['t_model_sec'] for r in s):7.2f}")
    print("\n  버거타임 ÷ 나머지 (중앙값 비, 날짜 단위 신뢰구간)")
    print(line("첫 응답 (판정 지표)", ratio_ci(cx, lambda r: r["t_first_output_sec"], rng)))
    print(line("CLI 준비 (세션 생성~프롬프트)", ratio_ci(with_phase, lambda r: r["t_prep_sec"], rng)))
    print(line("모델 응답 (프롬프트~답)", ratio_ci(with_phase, lambda r: r["t_model_sec"], rng)))
    wd = [r for r in with_phase if r["us_pacific_weekday"] < 5]
    we = [r for r in with_phase if r["us_pacific_weekday"] >= 5]
    print(line("모델 응답, 미국 평일만", ratio_ci(wd, lambda r: r["t_model_sec"], rng)))
    print(line("모델 응답, 미국 주말만", ratio_ci(we, lambda r: r["t_model_sec"], rng)))

    print("\n  요청 구성: 원격 플러그인 스킬 목록이 들어간 핑 / 안 들어간 핑")
    for flag, name in ((True, "들어감"), (False, "안 들어감")):
        s = [r for r in with_phase if r.get("remote_plugins") is flag]
        if not s:
            continue
        share_b = sum(1 for r in s if r["kst_hour"] in BURGER) / max(1, sum(1 for r in with_phase if r["kst_hour"] in BURGER))
        share_r = sum(1 for r in s if r["kst_hour"] not in BURGER) / max(1, sum(1 for r in with_phase if r["kst_hour"] not in BURGER))
        print(f"  {name:<6} {len(s)}건  입력 토큰 중앙값 {st.median(r['input_tokens'] for r in s):.0f}"
              f"  첫 응답 중앙값 {st.median(r['t_first_output_sec'] for r in s):.2f}초"
              f"  비중 버거타임 {share_b:.0%} / 나머지 {share_r:.0%}")
        print(line(f"  {name}: 첫 응답", ratio_ci(s, lambda r: r["t_first_output_sec"], rng)))

    cl = [r for r in pings if r.get("cli") == "claude" and isinstance(r.get("ttft_ms"), (int, float))]
    print(f"\nClaude 핑 (판정과 같은 기록, ttft 있는 것): {len(cl)}건")
    print(line("첫 응답 (판정 지표)", ratio_ci(cl, lambda r: r["t_first_output_sec"], rng)))
    print(line("API TTFT (CLI가 잰 첫 토큰)", ratio_ci(cl, lambda r: r["ttft_ms"] / 1000.0, rng)))
    local = [r["t_first_output_sec"] - r["ttft_ms"] / 1000.0 for r in cl]
    lb = [x for x, r in zip(local, cl) if r["kst_hour"] in BURGER]
    lr = [x for x, r in zip(local, cl) if r["kst_hour"] not in BURGER]
    print(f"  CLI 쪽 시간(첫 응답 − TTFT) 중앙값: 버거타임 {st.median(lb):.2f}초 / 나머지 {st.median(lr):.2f}초")


if __name__ == "__main__":
    main()
