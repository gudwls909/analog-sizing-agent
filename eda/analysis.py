"""동작점 분석: 스펙 숫자(gain, UGF)만으로는 안 보이는 "회로가 건강한가"를 판정한다.

증폭기 안의 트랜지스터는 전부 포화 영역에 여유 있게 있어야 한다.
포화 여유(margin) = |Vds| - Vdsat. 음수면 선형(triode) 영역 → 전류원·증폭 소자가 저항처럼 동작한다.
"""

from eda.spice import DEVICES

EDGE_V = 0.05  # 여유가 50mV보다 작으면 corner·온도·공정 편차로 쉽게 넘어간다


def check_operating_point(metrics, edge_v=EDGE_V):
    devices = []
    for d, (_, role) in DEVICES.items():
        vds, vdsat = abs(metrics[f"{d}_vds"]), abs(metrics[f"{d}_vdsat"])
        margin = vds - vdsat
        region = "triode" if margin < 0 else "edge" if margin < edge_v else "saturation"
        devices.append({
            "device": d, "role": role, "region": region,
            "vds": round(vds, 3), "vdsat": round(vdsat, 3), "margin_v": round(margin, 3),
            "id_ua": round(metrics[f"{d}_id"] * 1e6, 2),
            "intrinsic_gain": round(metrics[f"{d}_gm"] / metrics[f"{d}_gds"], 1),  # gm/gds: 소자 하나가 낼 수 있는 최대 이득
            # 약반전(subthreshold)은 저전력 설계에서 일부러 쓰기도 한다 → 문제가 아니라 정보로만 준다
            "weak_inversion": abs(metrics[f"{d}_vgs"]) < abs(metrics[f"{d}_vth"]),
        })
    problems = [x for x in devices if x["region"] != "saturation"]
    # tail이 bias 미러 전류를 제대로 복사하나 (선형 영역이면 덜 흘린다)
    mirror_ratio = metrics["mt_id"] / metrics["mb_id"]
    return {
        "healthy": not problems,
        "devices": devices,
        "tail_mirror_ratio": round(mirror_ratio, 3),
        "summary": "모든 트랜지스터가 포화 영역 (여유 ≥ 50mV)" if not problems else "; ".join(
            f"{x['device']}({x['role']}) {x['region']}: |Vds| {x['vds']}V vs Vdsat {x['vdsat']}V (여유 {x['margin_v'] * 1000:+.0f}mV)"
            for x in problems),
    }
