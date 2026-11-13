"""Agent가 쓰는 EDA 도구 4개. 결과는 짧게 요약한다 (도구가 무엇을 보여 주느냐가 Agent 정확도를 좌우한다 — exp-ops 4·5·13번).

- evaluate_design      : 15개 조건 전체 채점 (15회)
- inspect_operating_point: 한 조건의 트랜지스터별 동작 영역 (1회)
- sweep_parameter      : 한 손잡이를 여러 값으로, 한 조건에서 (값 개수만큼)
- local_search         : 숫자 미세 조정은 최적화기에 맡긴다 (LLM은 숫자 최적화에 약하다)
모든 도구는 시뮬레이션 예산을 확인하고, 범위 밖 값은 코드가 거부한다.
"""

import math
import random

from eda import spec, spice
from eda.analysis import check_operating_point


# shortcut: 전역 시뮬레이션 카운터 기준이라 한 프로세스에서 Agent를 동시에 여러 개 돌리면 서로의 사용량이 섞인다. 병렬 평가는 프로세스로 나눈다
class Budget:
    def __init__(self, limit):
        self.limit, self.start = limit, spice.stats["calls"]

    @property
    def used(self):
        return spice.stats["calls"] - self.start

    def check(self, need):
        if self.used + need > self.limit:
            return f"시뮬레이션 예산 부족: 남은 {self.limit - self.used}회, 필요 {need}회"


def _full(params):
    missing = set(spec.BOUNDS) - set(params)
    if missing:
        return None, f"손잡이 7개를 모두 줘야 한다. 빠짐: {sorted(missing)}"
    return params, spec.check_bounds(params)


def _summary(r):
    rows = [x for x in r["points"] if x["ok"]]
    out = {"passed": r["passed"], "score": None if math.isinf(r["score"]) else round(r["score"], 4),
           "failing_conditions": r["failing"][:8]}
    if rows:
        def worst(key, f):
            x = f(rows, key=lambda x: x["metrics"][key] if key != "margin" else x["worst_margin_v"])
            v = x["metrics"][key] if key != "margin" else x["worst_margin_v"]
            return {"value": round(v, 9 if key in ("power_w",) else 3), "at": f"{x['corner']} {x['temp']}C"}
        out["worst_case"] = {"gain_db": worst("gain_db", min), "ugf_hz": worst("ugf_hz", min),
                             "pm_deg": worst("pm_deg", min), "power_w": worst("power_w", max),
                             "sat_margin_v": worst("margin", min)}
    return out


def evaluate_design(budget, params):
    p, err = _full(params)
    err = err or budget.check(len(spec.ALL_POINTS))
    if err:
        return {"error": err}
    return _summary(spec.evaluate(p))


def inspect_operating_point(budget, params, corner, temp):
    p, err = _full(params)
    err = err or budget.check(1)
    if err:
        return {"error": err}
    r = spice.simulate(p, corner, temp)
    m = r["metrics"]
    if "m1_vds" not in m:
        return {"error": "동작점 계산 실패: " + (r["error"] or "")[:300]}
    op = check_operating_point(m)
    devices = []
    for d in op["devices"]:
        n = d["device"]
        devices.append({**d, "overdrive_mv": round((abs(m[f"{n}_vgs"]) - abs(m[f"{n}_vth"])) * 1000),
                        # gm/Id: 약 20 S/A 이상이면 약반전(gm이 W가 아니라 전류로 정해짐), 10 이하면 강반전
                        "gm_over_id": round(m[f"{n}_gm"] / abs(m[f"{n}_id"]), 1)})
    return {"corner": corner, "temp": temp, "measurement_ok": r["ok"], "measurement_error": r["error"],
            "metrics": {k: m[k] for k in ("gain_db", "ugf_hz", "pm_deg", "power_w", "vout_dc", "vtail") if k in m},
            "devices": devices, "tail_mirror_ratio": op["tail_mirror_ratio"]}


def sweep_parameter(budget, params, name, values, corner, temp):
    if name not in spec.BOUNDS or not 2 <= len(values) <= 8:
        return {"error": "name은 손잡이 이름, values는 2~8개"}
    p, err = _full(params)
    err = err or spec.check_bounds({name: min(values)}) or spec.check_bounds({name: max(values)}) or budget.check(len(values))
    if err:
        return {"error": err}
    rows = []
    for v in values:
        r = spice.simulate({**p, name: v}, corner, temp)
        m = r["metrics"]
        row = {name: v, "ok": r["ok"]}
        if r["ok"]:
            row |= {k: round(m[k], 9 if k == "power_w" else 3) for k in ("gain_db", "ugf_hz", "pm_deg", "power_w")}
            row["worst_margin_v"] = min(d["margin_v"] for d in check_operating_point(m)["devices"])
        else:
            row["error"] = r["error"].splitlines()[0]
        rows.append(row)
    return {"corner": corner, "temp": temp, "rows": rows}


def local_search(budget, params, knobs, iterations=30, step=0.15, conditions=None, seed=0):
    """(1+1) 진화 전략: 고른 손잡이만 로그 스케일로 흔들어 보고 나아지면 받아들인다.
    conditions(예: 가장 나쁜 조건 몇 개)에서만 채점해 아끼고, 끝에 15개 조건 전체로 검증한다."""
    p, err = _full(params)
    if err:
        return {"error": err}
    if not knobs or set(knobs) - set(spec.BOUNDS):
        return {"error": f"knobs는 {sorted(spec.BOUNDS)} 중에서"}
    pts = [(c, int(t)) for c, t in conditions] if conditions else spec.ALL_POINTS
    if set(pts) - set(spec.ALL_POINTS):
        return {"error": "conditions는 [corner, temp] 목록 (corner: tt ff ss sf fs, temp: -40 27 125)"}
    iterations = max(1, min(int(iterations), 60))
    err = budget.check(len(pts) + len(spec.ALL_POINTS))
    if err:
        return {"error": err}
    rng = random.Random(seed)
    clip = lambda q: {k: min(max(v, spec.BOUNDS[k][0]), spec.BOUNDS[k][1]) for k, v in q.items()}  # noqa: E731
    best, best_score, tried = p, spec.evaluate(p, pts)["score"], 0
    for _ in range(iterations):
        if budget.check(len(pts) + len(spec.ALL_POINTS)):  # 마지막 전체 검증 몫은 남긴다
            break
        cand = clip({k: v * (math.exp(rng.gauss(0, step)) if k in knobs else 1) for k, v in best.items()})
        s = spec.evaluate(cand, pts)["score"]
        tried += 1
        if s < best_score:
            best, best_score = cand, s
            if s == 0:  # 고른 조건을 통과하면 바로 전체로 확인
                break
    full = spec.evaluate(best)
    return {"tried": tried, "best_params": {k: float(f"{v:.4g}") for k, v in best.items()},
            "score_on_conditions": None if math.isinf(best_score) else round(best_score, 4),
            "full_check": _summary(full)}

