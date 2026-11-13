from eda import spec


def test_shortfall():
    assert spec.shortfall("gain_db", 43) == 0 and abs(spec.shortfall("gain_db", 37.8) - 0.1) < 1e-9
    assert spec.shortfall("power_w", 50e-6) == 0 and abs(spec.shortfall("power_w", 84e-6) - 0.2) < 1e-9
    assert 0 < spec.shortfall("ugf_hz", 10e6) < spec.shortfall("ugf_hz", 1e6)  # 주파수는 로그 배수


def test_bounds_block_fixed_and_out_of_range():
    assert "w_in" in spec.evaluate({"w_in": 999})["error"]
    assert "vcm" in spec.evaluate({"vcm": 1.1})["error"]  # 앞단이 정하는 값은 손잡이가 아님


def test_default_fails_on_gain_and_tail():
    r = spec.evaluate({}, spec.NOMINAL)
    assert not r["passed"] and "gain_db" in r["failing"][0] and "sat_margin" in r["failing"][0]


def test_spec_is_feasible():
    # 난이도 보정 표본에서 통과한 설계 하나 (해가 있다는 증거). 스펙을 바꾸면 이 테스트가 알려 준다
    import json
    rows = json.load(open("eval/results/sample_space.json"))
    ok = [r["params"] for r in rows if r["valid"] and r["gain_db"] >= 42 and r["power_w"] <= 70e-6
          and r["ugf_hz"] >= 20e6 and r["pm_deg"] >= 60 and r["margin_v"] >= 0.05]
    assert ok and spec.evaluate(ok[0])["passed"]
