"""스펙 난이도 보정용: 무작위 설계 N개를 15개 조건 전부에서 시뮬레이션하고 조건별 최악값만 저장한다.
스펙 후보마다 "무작위 설계 중 몇 %가 통과하나"를 시뮬레이션 없이 계산할 수 있다."""

import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from baselines.random_search import sample  # noqa: E402
from eda import spec  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
rng = random.Random(12345)  # random search seed(0~9)와 다른 표본
rows, t0 = [], time.time()
for i in range(N):
    p = sample(rng)
    r = spec.evaluate(p)
    ok = [x for x in r["points"] if x["ok"]]
    if len(ok) < len(spec.ALL_POINTS):
        rows.append({"params": p, "valid": False})
        continue
    rows.append({"params": p, "valid": True,
                 "gain_db": min(x["metrics"]["gain_db"] for x in ok),
                 "ugf_hz": min(x["metrics"]["ugf_hz"] for x in ok),
                 "pm_deg": min(x["metrics"]["pm_deg"] for x in ok),
                 "power_w": max(x["metrics"]["power_w"] for x in ok),
                 "margin_v": min(x["worst_margin_v"] for x in ok)})
    if (i + 1) % 500 == 0:
        print(f"{i + 1}/{N}  {time.time() - t0:.0f}s", flush=True)
json.dump(rows, open("eval/results/sample_space.json", "w"))
print("저장: eval/results/sample_space.json")
