"""베이스라인 1: Random Search. 아무 지식 없이 범위 안에서 무작위로 뽑는다 (W·L·전류는 로그 균등).
먼저 TT 27°C 한 조건으로 거르고, 통과한 후보만 15개 조건 전체로 검증한다 (설계자도 이렇게 한다).
비용 = 시뮬레이션 횟수 (조건 하나 = 1회)."""

import argparse
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eda import spec  # noqa: E402


def sample(rng):
    return {k: math.exp(rng.uniform(math.log(lo), math.log(hi))) for k, (lo, hi) in spec.BOUNDS.items()}


def run(budget, seed):
    rng = random.Random(seed)
    sims, best = 0, (math.inf, None)
    while sims < budget:
        p = sample(rng)
        r = spec.evaluate(p, spec.NOMINAL)
        sims += 1
        best = min(best, (r["score"], p), key=lambda x: x[0])
        if r["passed"]:
            full = spec.evaluate(p)
            sims += len(spec.ALL_POINTS)
            if full["passed"]:
                return {"seed": seed, "solved": True, "sims": sims, "params": p}
    return {"seed": seed, "solved": False, "sims": sims, "best_nominal_score": best[0], "best_params": best[1]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--seeds", type=int, default=10)
    a = ap.parse_args()
    t0, out = time.time(), []
    for s in range(a.seeds):
        r = run(a.budget, s)
        out.append(r)
        print(f"seed {s}: {'해결' if r['solved'] else '실패'}  시뮬레이션 {r['sims']}회", flush=True)
    solved = [r["sims"] for r in out if r["solved"]]
    print(f"\n해결 {len(solved)}/{a.seeds}, 해결까지 시뮬레이션 중앙값 "
          f"{sorted(solved)[len(solved) // 2] if solved else '-'}, 전체 {time.time() - t0:.0f}초")
    path = f"eval/results/random_search_b{a.budget}.json"
    json.dump(out, open(path, "w"), indent=1)
    print("저장:", path)
