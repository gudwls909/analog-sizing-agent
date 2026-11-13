"""규칙 기반과 같은 시작점(기본값 + 무작위 1000~1009)에서 Agent를 돌린다. 시작점 하나 = 결과 파일 하나.
python eval/run_agent.py 0 3 5   # 0 = 기본값, 1~10 = 무작위 0~9"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import agent  # noqa: E402
from baselines.random_search import sample  # noqa: E402
from eda import spec, spice  # noqa: E402

for i in map(int, sys.argv[1:]):
    name, st = ("기본값", {k: spice.DEFAULT[k] for k in spec.BOUNDS}) if i == 0 else (f"무작위 {i - 1}", sample(random.Random(1000 + i - 1)))
    r = agent.run(st, sim_budget=2000)
    r["start"] = name
    t = r["trace"]
    print(f"{name}: {'해결' if r['solved'] else '실패 — ' + r['reason'][:80]}  시뮬레이션 {r['sims']}회, LLM {t['llm_calls']}회, ${t['cost_usd']}, {t['latency_s']}s", flush=True)
    json.dump(r, open(f"eval/results/agent_gain{spec.SPEC['gain_db'][1]:.0f}_start{i}.json", "w"), ensure_ascii=False, indent=1, default=str)
