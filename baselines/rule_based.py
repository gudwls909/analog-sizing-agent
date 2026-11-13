"""베이스라인 2: 교과서 규칙으로 고치기. 설계자가 손으로 하는 반복을 코드로 옮긴 것.

매 반복: 15개 조건 전체 평가 → 가장 나쁜 조건에서 가장 급한 문제 하나 → 규칙 하나 적용.
우선순위: 포화 여유(회로가 건강해야 나머지 숫자가 의미 있음) > 전력 > gain > UGF > PM.

규칙 (모두 W/L 비율이나 전류에 대한 1차 근사)
- 트랜지스터가 포화 여유 부족 → 그 소자 W ×1.5 (같은 전류에 Vdsat ↓)
- 전력 초과                    → ibias ×0.9
- gain 부족                    → 입력쌍·부하 L ×1.3, W도 ×1.3 (W/L 유지 → gm 유지, ro ↑)
- UGF 부족                     → 전력 여유가 있으면 ibias ×1.1, 없으면 입력쌍 W ×1.3 (gm ↑)
- PM 부족                      → 부하 L ×0.8 (미러 극점의 기생 C ↓)
비용 = 시뮬레이션 횟수 (반복마다 15회).
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from baselines.random_search import sample  # noqa: E402
from eda import spec, spice  # noqa: E402

# 소자 -> 그 소자의 W 파라미터 (tail과 bias 미러는 같은 W를 쓴다)
DEVICE_W = {"mb": "w_tail", "mt": "w_tail", "m1": "w_in", "m2": "w_in", "m3": "w_load", "m4": "w_load"}


def clip(p):
    return {k: min(max(v, spec.BOUNDS[k][0]), spec.BOUNDS[k][1]) for k, v in p.items()}


def worst_point(r):
    return max(r["points"], key=lambda x: sum(x["gaps"].values()))


def choose_rule(r):
    """가장 나쁜 조건 하나를 보고 규칙 하나를 고른다. (규칙 이름, 바꿀 값들)"""
    w = worst_point(r)
    g, m = w["gaps"], w["metrics"]
    if g["sat_margin"] > 0:
        # 동작점 요약에서 여유가 가장 작은 소자를 찾는다
        dev = min(w["devices"], key=lambda d: d["margin_v"])["device"]
        return f"{dev} 포화 여유 부족 → {DEVICE_W[dev]} ×1.5", {DEVICE_W[dev]: 1.5}
    if g["power_w"] > 0:
        return "전력 초과 → ibias ×0.9", {"ibias": 0.9}
    if g["gain_db"] > 0:
        return "gain 부족 → 입력쌍·부하 L, W ×1.3", {"l_in": 1.3, "w_in": 1.3, "l_load": 1.3, "w_load": 1.3}
    if g["ugf_hz"] > 0:
        # 전력 여유는 최악 조건이 아니라 모든 조건의 최대 전력으로 본다 (아니면 UGF↑/전력↓가 서로 다른 corner에서 핑퐁)
        if max(x["metrics"]["power_w"] for x in r["points"]) < spec.SPEC["power_w"][1] * 0.9:
            return "UGF 부족 (전력 여유 있음) → ibias ×1.1", {"ibias": 1.1}
        return "UGF 부족 (전력 여유 없음) → 입력쌍 W ×1.3", {"w_in": 1.3}
    return "PM 부족 → 부하 L ×0.8", {"l_load": 0.8}


def run(start, budget, patience=8):
    p, sims, history = clip(dict(start)), 0, []
    best = float("inf")
    stale = 0
    while sims + len(spec.ALL_POINTS) <= budget:
        r = spec.evaluate(p)
        sims += len(spec.ALL_POINTS)
        if r["score"] == float("inf"):
            bad = next(x for x in r["points"] if not x["ok"])  # 규칙이 없는 경우: 어떤 corner에서 증폭기로 동작하지 않음
            return {"solved": False, "sims": sims, "history": history,
                    "reason": f"측정 실패 ({bad['corner']} {bad['temp']}°C): " + bad["error"].splitlines()[0]}
        if r["passed"]:
            return {"solved": True, "sims": sims, "params": p, "history": history}
        if r["score"] < best - 1e-6:
            best, stale = r["score"], 0
        else:
            stale += 1
            if stale >= patience:  # 같은 규칙이 서로 상쇄되며 맴돈다
                return {"solved": False, "sims": sims, "reason": f"{patience}번 연속 개선 없음 (맴돎)", "best_score": best, "params": p,
                        "history": history}
        rule, change = choose_rule(r)
        w = worst_point(r)
        history.append({"score": round(r["score"], 3), "worst": f"{w['corner']} {w['temp']}°C", "rule": rule})
        p = clip({k: v * change.get(k, 1.0) for k, v in p.items()})
    return {"solved": False, "sims": sims, "reason": "예산 소진", "best_score": best, "history": history}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--starts", type=int, default=10)
    a = ap.parse_args()
    starts = [("기본값", {k: spice.DEFAULT[k] for k in spec.BOUNDS})]
    starts += [(f"무작위 {s}", sample(random.Random(1000 + s))) for s in range(a.starts)]
    out = []
    for name, st in starts:
        r = run(st, a.budget)
        r["start"] = name
        out.append(r)
        print(f"{name}: {'해결' if r['solved'] else '실패 — ' + r['reason']}  시뮬레이션 {r['sims']}회, 규칙 {len(r['history'])}번", flush=True)
    path = f"eval/results/rule_based_gain{spec.SPEC['gain_db'][1]:.0f}_b{a.budget}.json"
    json.dump(out, open(path, "w"), indent=1, ensure_ascii=False)
    print("저장:", path)
