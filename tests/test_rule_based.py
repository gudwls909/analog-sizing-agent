from baselines import rule_based
from eda import spec


def point(corner, temp, power, ugf, sat=0.0):
    gaps = {k: 0.0 for k in spec.SPEC} | {"sat_margin": sat, "ugf_hz": ugf}
    return {"corner": corner, "temp": temp, "ok": True, "gaps": gaps,
            "metrics": {"power_w": power, "gain_db": 45, "ugf_hz": 1.5e7, "pm_deg": 80},
            "devices": [{"device": "mt", "region": "edge", "margin_v": 0.02}]}


def test_power_headroom_uses_worst_corner():
    # UGF가 부족한 조건은 전력 여유가 있지만, 다른 corner가 이미 전력 한계 근처 → 전류를 올리면 안 된다
    r = {"points": [point("ff", -40, 40e-6, 0.1), point("fs", 125, 68e-6, 0.0)]}
    rule, change = rule_based.choose_rule(r)
    assert "ibias" not in change and "w_in" in change


def test_saturation_first():
    rule, change = rule_based.choose_rule({"points": [point("tt", 27, 40e-6, 0.1, sat=0.5)]})
    assert change == {"w_tail": 1.5}
