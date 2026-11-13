"""ngspice 실행 + 측정값 추출. Agent 도구들이 이 위에 올라간다.

simulate(params, corner, temp) -> {"ok", "metrics", "error", "sim_time_s"}
시뮬레이션 호출 횟수·시간은 평가 지표(스펙 달성까지 몇 번 돌렸나)라서 여기서 센다.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIRCUIT = os.path.join(ROOT, "circuits", "ota5t.cir")
SPICEINIT = os.path.join(ROOT, "circuits", ".spiceinit")
PDK = os.getenv("PDK_ROOT", os.path.expanduser("~/pdk")) + "/sky130A"
NGSPICE = shutil.which("ngspice") or os.path.expanduser("~/anaconda3/envs/eda-agent/bin/ngspice")

# 검증된 시작점 (TT: gain 36.5dB, UGF 22MHz, PM 89.5°, 67uW). 단위: W/L um
DEFAULT = {"ibias": 20e-6, "wt": 4, "lt": 1, "wn": 4, "ln": 0.5, "wp": 4, "lp": 0.5, "cl": 1e-12, "vcm": 0.9}
CORNERS = ["tt", "ff", "ss", "sf", "fs"]
METRIC = re.compile(r"^(\w+)\s*=\s*([-+0-9.eE]+)\s*$")

stats = {"calls": 0, "time_s": 0.0}


def simulate(params=None, corner="tt", temp=27, timeout=120):
    p = {**DEFAULT, **(params or {})}
    if corner not in CORNERS:
        return {"ok": False, "metrics": {}, "error": f"모르는 corner: {corner}", "sim_time_s": 0.0}
    netlist = open(CIRCUIT).read().format(pdk=PDK, corner=corner, temp=temp, **p)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:  # 실행마다 따로: corner 병렬 실행 가능
        shutil.copy(SPICEINIT, d)
        open(os.path.join(d, "run.cir"), "w").write(netlist)
        try:
            r = subprocess.run([NGSPICE, "-b", "run.cir"], cwd=d, capture_output=True, text=True, timeout=timeout)
            out, code = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired:
            out, code = "", "timeout"
    dt = time.time() - t0
    stats["calls"] += 1
    stats["time_s"] += dt

    metrics = {}
    for line in out.splitlines():
        m = METRIC.match(line.strip())
        if m:
            metrics[m.group(1)] = float(m.group(2))
    missing = [k for k in ("gain_db", "ugf_hz", "pm_deg", "power_w") if k not in metrics]
    if code != 0 or missing:
        # 오류 분석 도구가 읽을 수 있게 마지막 줄들을 남긴다 (예: UGF가 없음 = gain이 0dB를 안 넘음)
        tail = "\n".join(l for l in out.splitlines() if "rror" in l or "arning" in l or "fail" in l.lower())[-1500:]
        return {"ok": False, "metrics": metrics, "error": f"exit={code}, 측정 누락={missing}\n{tail}", "sim_time_s": dt}
    if metrics["ugf_hz"] <= 10 or metrics["gain_db"] <= 0:
        # 바이어스가 사실상 0이면 누설 전류 때문에 10Hz 아래에서 0dB 교차가 "측정"된다. 숫자는 나오지만 의미 없음
        return {"ok": False, "metrics": metrics, "sim_time_s": dt,
                "error": f"측정 무효: gain(10Hz)={metrics['gain_db']:.1f}dB, UGF={metrics['ugf_hz']:.1f}Hz — 회로가 증폭기로 동작하지 않음 (바이어스 확인)"}
    return {"ok": True, "metrics": metrics, "error": None, "sim_time_s": dt}
