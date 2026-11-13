"""동작점 분석 도구. 단위 테스트(가짜 값)와 실제 시뮬레이션 둘 다"""
from eda import spice
from eda.analysis import check_operating_point


def fake(**over):
    m = {}
    for d in spice.DEVICES:
        m.update({f"{d}_id": 1e-5, f"{d}_gm": 1e-4, f"{d}_gds": 1e-6, f"{d}_vgs": 0.8, f"{d}_vds": 0.5, f"{d}_vth": 0.6, f"{d}_vdsat": 0.15})
    m.update(over)
    return m


def test_regions_and_pmos_sign():
    r = check_operating_point(fake(mt_vds=0.14, m1_vds=0.18, m4_vds=-0.5, m4_vdsat=-0.15))  # PMOS는 음수로 와도 크기로 판단
    reg = {x["device"]: x["region"] for x in r["devices"]}
    assert reg["mt"] == "triode" and reg["m1"] == "edge" and reg["m4"] == "saturation"
    assert not r["healthy"] and "mt(tail 전류원) triode" in r["summary"]


def test_default_ota_tail_in_triode_and_fix():
    # 기본 사이징: 스펙(36.5dB, 22MHz, PM 89°)은 멀쩡한데 tail이 선형 영역 → 미러 전류를 덜 복사
    bad = check_operating_point(spice.simulate()["metrics"])
    assert not bad["healthy"] and bad["devices"][1]["device"] == "mt" and bad["devices"][1]["region"] == "triode"
    assert bad["tail_mirror_ratio"] < 0.9
    # 입력 공통 전압을 올리면 tail 노드가 올라가 포화로 들어간다
    good = check_operating_point(spice.simulate({"vcm": 1.1})["metrics"])
    assert good["healthy"], good["summary"]
    assert good["tail_mirror_ratio"] > 0.95
