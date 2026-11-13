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
    assert not spice.simulate(corner="xx")["ok"]


def test_corners_run_in_parallel():
    with ThreadPoolExecutor(3) as ex:
        rs = list(ex.map(lambda c: spice.simulate(corner=c), ["tt", "ff", "ss"]))
    assert all(r["ok"] for r in rs)
    gains = [r["metrics"]["gain_db"] for r in rs]
    assert len(set(round(g, 2) for g in gains)) == 3  # corner마다 실제로 다른 모델이 걸렸다
