"""실제 ngspice + SKY130으로 돈다 (1회 약 10초)"""
from concurrent.futures import ThreadPoolExecutor

from eda import spice


def test_default_ota_tt():
    r = spice.simulate()
    assert r["ok"], r["error"]
    m = r["metrics"]
    assert 30 < m["gain_db"] < 45 and 1e7 < m["ugf_hz"] < 1e8 and 60 < m["pm_deg"] < 100 and m["power_w"] < 1e-4


def test_failure_is_reported_not_raised():
    r = spice.simulate({"ibias": 1e-12})  # 바이어스가 거의 0
    assert not r["ok"] and "측정 무효" in r["error"]  # 숫자는 나오지만(UGF 7Hz) 쓸 수 없는 증폭기
    assert not spice.simulate(corner="xx")["ok"] and not spice.simulate(temp=50)["ok"]


def test_corners_run_in_parallel():
    with ThreadPoolExecutor(3) as ex:
        rs = list(ex.map(lambda c: spice.simulate(corner=c), ["tt", "ff", "ss"]))
    assert all(r["ok"] for r in rs)
    gains = [r["metrics"]["gain_db"] for r in rs]
    assert len(set(round(g, 2) for g in gains)) == 3  # corner마다 실제로 다른 모델이 걸렸다


def test_session_reuse_matches_and_no_state_leak():
    a = spice.simulate()
    spice.simulate({"w_in": 16, "ibias": 40e-6})  # 같은 세션에서 다른 값으로
    b = spice.simulate()  # 기본값으로 돌아왔나 (앞 요청의 값이 남으면 안 됨)
    assert a["metrics"]["gain_db"] == b["metrics"]["gain_db"] and a["metrics"]["ugf_hz"] == b["metrics"]["ugf_hz"]
    assert abs(a["metrics"]["gain_db"] - 36.533) < 0.01  # 세션 방식 전(batch 실행)과 같은 값
    assert b["sim_time_s"] < 1.0  # 로딩은 한 번만


def test_temperature_is_applied():
    g = {t: spice.simulate(temp=t)["metrics"]["ugf_hz"] for t in (-40, 125)}
    assert g[-40] > g[125] * 1.2  # 차가울수록 빠르다 (25 vs 19MHz)


def test_unknown_param_rejected():
    assert "모르는 파라미터" in spice.simulate({"w_typo": 3})["error"]
