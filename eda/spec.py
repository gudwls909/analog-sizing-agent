"""설계 스펙과 채점. Agent·최적화기·평가가 모두 이 기준 하나를 쓴다.

성공 = 5 corner × 3 온도 = 15개 조건 전부에서 성능 스펙을 만족하고, 모든 트랜지스터가 포화 여유 ≥ 50mV.
"""

import math
from concurrent.futures import ThreadPoolExecutor

from eda import spice
from eda.analysis import EDGE_V, check_operating_point

# 성능 스펙: 이름 -> (방향, 값)
SPEC = {
    "gain_db": (">=", 40.0),
    "ugf_hz": (">=", 20e6),
    "pm_deg": (">=", 60.0),
    "power_w": ("<=", 100e-6),
}

# 설계자가 바꿀 수 있는 손잡이와 범위. vcm(앞단이 정함)과 cl(부하)은 문제 조건이라 고정
BOUNDS = {
    "ibias": (5e-6, 50e-6),
    "w_tail": (1.0, 50.0), "l_tail": (0.15, 4.0),
    "w_in": (1.0, 50.0), "l_in": (0.15, 4.0),
    "w_load": (1.0, 50.0), "l_load": (0.15, 4.0),
}
ALL_POINTS = [(c, t) for c in spice.CORNERS for t in spice.TEMPS]
NOMINAL = [("tt", 27)]


def check_bounds(params):
    bad = {k: v for k, v in params.items() if k not in BOUNDS or not BOUNDS[k][0] <= v <= BOUNDS[k][1]}
    return f"범위 밖이거나 바꿀 수 없는 파라미터: {bad}" if bad else None


def shortfall(name, value):
    """스펙 대비 상대 부족분. 0이면 만족. 최적화기가 '얼마나 가까운가'를 알 수 있게"""
    op, target = SPEC[name]
    if name == "ugf_hz":  # 주파수는 배수로 본다 (10MHz는 20MHz의 절반 = 0.5 부족)
        value, target = math.log10(max(value, 1.0)), math.log10(target)
    gap = (target - value) if op == ">=" else (value - target)
    return max(0.0, gap / abs(target))


def evaluate(params, points=ALL_POINTS):
    """params를 points의 모든 조건에서 시뮬레이션하고 채점한다.
    반환: passed, score(0이면 통과, 클수록 멀다), 조건별 결과, 최악 조건 요약"""
    err = check_bounds(params)
    if err:
        return {"passed": False, "score": math.inf, "error": err, "points": []}
    with ThreadPoolExecutor(len(points)) as ex:  # 조건마다 세션이 따로라 병렬로 돈다
        results = list(ex.map(lambda ct: spice.simulate(params, *ct), points))

    rows, score = [], 0.0
    for (corner, temp), r in zip(points, results):
        if not r["ok"]:
            rows.append({"corner": corner, "temp": temp, "ok": False, "error": r["error"]})
            score = math.inf
            continue
        m = r["metrics"]
        op = check_operating_point(m)
        gaps = {k: shortfall(k, m[k]) for k in SPEC}
        worst_margin = min(d["margin_v"] for d in op["devices"])
        gaps["sat_margin"] = max(0.0, (EDGE_V - worst_margin) / EDGE_V)
        rows.append({"corner": corner, "temp": temp, "ok": True,
                     "metrics": {k: m[k] for k in SPEC}, "worst_margin_v": worst_margin,
                     "op_summary": op["summary"], "gaps": gaps})
        score = max(score, sum(gaps.values()))  # 최악 조건 기준
    passed = score == 0.0
    failing = [r for r in rows if not r["ok"] or sum(r["gaps"].values()) > 0]
    return {"passed": passed, "score": score, "points": rows,
            "failing": [f"{r['corner']} {r['temp']}°C: " + (r.get("error") or ", ".join(
                f"{k} 부족 {v:.1%}" for k, v in r["gaps"].items() if v > 0)) for r in failing]}
