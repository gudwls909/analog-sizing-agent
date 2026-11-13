"""규칙 기반과 같은 시작점(기본값 + 무작위 1000~1009)에서 Agent를 돌린다. 시작점 하나 = 결과 파일 하나.
python eval/run_agent.py --guard 1 --repeat 0 0 3 5   # 0 = 기본값, 1~10 = 무작위 0~9"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent import agent  # noqa: E402
from baselines.random_search import sample  # noqa: E402
from eda import spec, spice  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--guard", type=int, default=1)
ap.add_argument("--repeat", type=int, default=0)
ap.add_argument("--handoff", type=int, default=0)
ap.add_argument("--set", choices=["dev", "heldout"], default="dev")  # heldout: 무작위 5000~5009, 결과를 보고 Agent를 고치지 않는다
ap.add_argument("starts", type=int, nargs="+")
a = ap.parse_args()
tag = f"{'heldout_' if a.set == 'heldout' else ''}{'guard' if a.guard else 'noguard'}{'_handoff' if a.handoff else ''}_r{a.repeat}"
for i in a.starts:
    if a.set == "heldout":
        name, st = f"held-out {i}", sample(random.Random(5000 + i))
    else:
        name, st = ("기본값", {k: spice.DEFAULT[k] for k in spec.BOUNDS}) if i == 0 else (f"무작위 {i - 1}", sample(random.Random(1000 + i - 1)))
    r = agent.run(st, sim_budget=2000, guard=bool(a.guard), handoff=bool(a.handoff))
    r["start"] = name
    t = r["trace"]
    print(f"{tag} {name}: {'해결' if r['solved'] else '실패 — ' + r['reason'][:80]}  시뮬레이션 {r['sims']}회, LLM {t['llm_calls']}회, ${t['cost_usd']}, {t['latency_s']}s", flush=True)
    r.pop("messages")  # LLM 대화 기록은 저장하지 않는다 (요약·trace만)
    json.dump(r, open(f"eval/results/agent_gain{spec.SPEC['gain_db'][1]:.0f}_{tag}_start{i}.json", "w"), ensure_ascii=False, indent=1, default=str)
