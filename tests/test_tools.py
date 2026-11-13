"""Agent 도구: LLM 없이 실제 시뮬레이션으로"""
from eda import spec, spice, tools

P = {k: spice.DEFAULT[k] for k in spec.BOUNDS}


def test_evaluate_and_inspect_default():
    b = tools.Budget(100)
    r = tools.evaluate_design(b, P)
    assert not r["passed"] and r["worst_case"]["sat_margin_v"]["value"] < 0 and b.used == 15
    op = tools.inspect_operating_point(b, P, "fs", 125)
    mt = next(d for d in op["devices"] if d["device"] == "mt")
    assert mt["region"] == "triode" and mt["gm_over_id"] > 0 and b.used == 16


def test_code_enforced_limits():
    b = tools.Budget(20)
    assert "빠짐" in tools.evaluate_design(b, {"ibias": 2e-5})["error"]
    assert "범위" in tools.evaluate_design(b, {**P, "w_in": 500})["error"]
    assert "범위" in tools.sweep_parameter(b, P, "w_in", [10, 500], "tt", 27)["error"]
    tools.evaluate_design(b, P)
    assert "예산" in tools.evaluate_design(b, P)["error"] and b.used == 15  # 예산을 넘는 호출은 돌지 않는다


def test_sweep_and_local_search_spend_budget():
    b = tools.Budget(200)
    s = tools.sweep_parameter(b, P, "l_in", [0.5, 1, 2], "tt", 27)
    assert [r["l_in"] for r in s["rows"]] == [0.5, 1, 2] and all("worst_margin_v" in r for r in s["rows"]) and b.used == 3
    r = tools.local_search(b, P, ["w_tail"], iterations=3, conditions=[["fs", 125]])
    assert "full_check" in r and b.used <= 200
