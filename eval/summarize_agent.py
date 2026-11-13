"""두 조건의 Agent 결과를 시작점별로 짝지어 비교한다. 시작점 단위 bootstrap 95% CI (해결률 차이).
python eval/summarize_agent.py noguard guard
python eval/summarize_agent.py guard guard_handoff"""

import glob
import json
import random
import re
import statistics
import sys
from collections import defaultdict

A, B = sys.argv[1:3] if len(sys.argv) > 2 else ("noguard", "guard")

runs = defaultdict(lambda: defaultdict(list))  # cond -> start index -> [run]
for f in glob.glob("eval/results/agent_gain42_*_r*_start*.json"):
    cond, start = re.search(r"agent_gain42_(.+)_r\d+_start(\d+)\.json$", f).groups()
    runs[cond][int(start)].append(json.load(open(f)))

starts = sorted(set(runs[A]) & set(runs[B]))
rate = {c: {s: statistics.mean(r["solved"] for r in runs[c][s]) for s in starts} for c in (A, B)}

for c in (A, B):
    allr = [r for s in starts for r in runs[c][s]]
    solved = [r["sims"] for r in allr if r["solved"]]
    fails = defaultdict(int)
    for r in allr:
        if not r["solved"]:
            fails[r["reason"].split(":")[0]] += 1
    print(f"{c:8} 해결 {len(solved)}/{len(allr)}  시뮬레이션 중앙값 {statistics.median(solved) if solved else '-'}"
          f"  비용 합 ${sum(r['trace']['cost_usd'] for r in allr):.2f}"
          f"  LLM 호출 중앙값 {statistics.median(r['trace']['llm_calls'] for r in allr)}"
          f"  거부 합 {sum(r['trace'].get('guard_refusals', 0) for r in allr)}  넘김 {sum(len(r['trace'].get('handoffs', [])) for r in allr)}  실패 이유 {dict(fails)}")

print(f"\n시작점별 해결률 ({A} → {B})")
for s in starts:
    print(f"  start{s:<3} {rate[A][s]:.2f} → {rate[B][s]:.2f}   (n={len(runs[A][s])}, {len(runs[B][s])})")

diff = [rate[B][s] - rate[A][s] for s in starts]
rng = random.Random(0)
boots = sorted(statistics.mean(rng.choice(diff) for _ in diff) for _ in range(10000))
print(f"\n해결률 차이({B} − {A}) 평균 {statistics.mean(diff):+.3f}, 95% CI [{boots[250]:+.3f}, {boots[9750]:+.3f}]  (시작점 {len(starts)}개 짝)")
