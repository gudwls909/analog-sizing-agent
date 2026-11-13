from eda import spec


def test_shortfall():
    assert spec.shortfall("gain_db", 41) == 0 and abs(spec.shortfall("gain_db", 36) - 0.1) < 1e-9
    assert spec.shortfall("power_w", 50e-6) == 0 and abs(spec.shortfall("power_w", 120e-6) - 0.2) < 1e-9
    assert 0 < spec.shortfall("ugf_hz", 10e6) < spec.shortfall("ugf_hz", 1e6)  # 주파수는 로그 배수


def test_bounds_block_fixed_and_out_of_range():
    assert "w_in" in spec.evaluate({"w_in": 999})["error"]
    assert "vcm" in spec.evaluate({"vcm": 1.1})["error"]  # 앞단이 정하는 값은 손잡이가 아님


def test_default_fails_on_gain_and_tail():
    r = spec.evaluate({}, spec.NOMINAL)
    assert not r["passed"] and "gain_db" in r["failing"][0] and "sat_margin" in r["failing"][0]
