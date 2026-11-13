"""ngspice 실행 + 측정값 추출. Agent 도구들이 이 위에 올라간다.

simulate(params, corner, temp) -> {"ok", "metrics", "error", "sim_time_s"}

속도: SKY130 모델 로딩이 11초, 실제 계산(op + AC)은 0.05초다. 그래서 (corner, 온도)마다 ngspice를
pipe 모드로 한 번 띄워 두고, 파라미터만 alterparam으로 바꿔 다시 계산한다.
온도는 실행 중에 바뀌지 않아서(option temp 무시됨) 온도도 세션 단위다. 세션 하나 약 350MB.
시뮬레이션 호출 횟수·시간은 평가 지표라서 여기서 센다.
"""

import atexit
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CIRCUIT = os.path.join(ROOT, "circuits", "ota5t.cir")
SPICEINIT = os.path.join(ROOT, "circuits", ".spiceinit")
PDK = os.getenv("PDK_ROOT", os.path.expanduser("~/pdk")) + "/sky130A"
NGSPICE = shutil.which("ngspice") or os.path.expanduser("~/anaconda3/envs/eda-agent/bin/ngspice")

# 검증된 시작점 (TT 27°C: gain 36.5dB, UGF 22MHz, PM 89.5°, 67uW. 단 tail이 선형 영역). 단위: W/L um
DEFAULT = {"ibias": 20e-6, "w_tail": 4, "l_tail": 1, "w_in": 4, "l_in": 0.5, "w_load": 4, "l_load": 0.5, "cl": 1e-12, "vcm": 0.9}
CORNERS = ["tt", "ff", "ss", "sf", "fs"]
TEMPS = [-40, 27, 125]
METRIC = re.compile(r"^(?:\w+\.)?(\w+)\s*=\s*([-+0-9.eE]+)\s*$")  # ngspice가 "op1.", "const." 접두어를 붙인다

# 동작점을 볼 트랜지스터: 이름 -> (ngspice 내부 경로, 역할). SKY130 소자는 subckt 안의 M 소자다
DEVICES = {
    "mb": ("xmb.msky130_fd_pr__nfet_01v8", "bias 미러 (다이오드 연결)"),
    "mt": ("xmt.msky130_fd_pr__nfet_01v8", "tail 전류원"),
    "m1": ("xm1.msky130_fd_pr__nfet_01v8", "입력쌍 (+)"),
    "m2": ("xm2.msky130_fd_pr__nfet_01v8", "입력쌍 (-)"),
    "m3": ("xm3.msky130_fd_pr__pfet_01v8", "부하 미러 (다이오드 연결)"),
    "m4": ("xm4.msky130_fd_pr__pfet_01v8", "부하 미러 (출력)"),
}
OP_PARAMS = ["id", "gm", "gds", "vgs", "vds", "vth", "vdsat"]

MEASURE = "\n".join([
    "destroy all",  # 이전 실행의 벡터가 남아 있으면 측정 실패가 옛 값으로 가려진다. 메모리도 계속 는다
    "op",
    "let power_w = -i(vdd)*1.8", "let vout_dc = v(out)", "let vtail = v(tail)",
    "print power_w vout_dc vtail",
    *[f"let {d}_{q} = @m.{path}[{q}]" for d, (path, _) in DEVICES.items() for q in OP_PARAMS],
    "print " + " ".join(f"{d}_{q}" for d in DEVICES for q in OP_PARAMS),
    "ac dec 50 1 10G",
    "meas ac gain_db find vdb(out) at=10",
    "meas ac ugf_hz when vdb(out)=0",
    "meas ac phase_ugf find vp(out) at=ugf_hz",
    "let pm_deg = 180 + phase_ugf*180/pi",
    "print pm_deg",
])

stats = {"calls": 0, "time_s": 0.0, "sessions_started": 0}


class Session:
    """(corner, 온도) 하나에 대한 살아 있는 ngspice. 한 번에 한 요청만 (lock)"""

    def __init__(self, corner, temp):
        self.key = (corner, temp)
        self.lock = threading.Lock()
        self.dir = tempfile.mkdtemp(prefix=f"ngspice_{corner}_{temp}_")
        shutil.copy(SPICEINIT, self.dir)
        netlist = open(CIRCUIT).read().replace("__PDK__", PDK).replace("__CORNER__", corner).replace("__TEMP__", str(temp))
        open(os.path.join(self.dir, "run.cir"), "w").write(netlist)
        self.proc = subprocess.Popen([NGSPICE, "-p", "run.cir"], cwd=self.dir, text=True, bufsize=1,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stats["sessions_started"] += 1

    def run(self, commands):
        # shortcut: 응답 시간 제한 없음. ngspice가 수렴 못 하고 멈추면 여기서 기다린다 → 그런 일이 보이면 읽기 스레드 + timeout으로
        self.proc.stdin.write(commands + "\necho __DONE__\n")
        self.proc.stdin.flush()
        out = []
        for line in self.proc.stdout:
            if line.strip() == "__DONE__":
                return "".join(out)
            out.append(line)
            if "y/n ?" in line:  # 넷리스트 오류 시 ngspice가 확인을 묻는데, 다음 명령을 답으로 먹으며 무한히 반복한다
                self.close()
                raise RuntimeError(f"ngspice 세션 {self.key} 넷리스트 오류:\n" + "".join(l for l in out if "err" in l.lower())[:1500])
        raise RuntimeError(f"ngspice 세션 {self.key} 종료됨:\n" + "".join(out[-20:]))

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.dir, ignore_errors=True)


_sessions = {}
_sessions_lock = threading.Lock()


def _session(corner, temp):
    with _sessions_lock:
        s = _sessions.get((corner, temp))
        if s is None or s.proc.poll() is not None:
            s = _sessions[(corner, temp)] = Session(corner, temp)
        return s


@atexit.register
def close_all():
    with _sessions_lock:
        for s in _sessions.values():
            s.close()
        _sessions.clear()


def simulate(params=None, corner="tt", temp=27):
    unknown = set(params or {}) - set(DEFAULT)
    if unknown:  # alterparam에 모르는 이름을 주면 ngspice는 경고만 하고 계속 돈다 → 여기서 막는다
        return {"ok": False, "metrics": {}, "error": f"모르는 파라미터: {sorted(unknown)}", "sim_time_s": 0.0}
    if corner not in CORNERS or temp not in TEMPS:
        return {"ok": False, "metrics": {}, "error": f"지원하지 않는 조건: {corner}, {temp}°C", "sim_time_s": 0.0}
    p = {**DEFAULT, **(params or {})}
    # 매번 전부 다시 설정한다: 앞 요청이 바꾼 값이 세션에 남아 다음 요청에 섞이면 안 된다
    cmds = "\n".join(f"alterparam {k}={v:g}" for k, v in p.items()) + "\nreset\n" + MEASURE
    s = _session(corner, temp)
    t0 = time.time()
    with s.lock:
        try:
            out, crashed = s.run(cmds), None
        except RuntimeError as e:
            out, crashed = "", str(e)
    dt = time.time() - t0
    stats["calls"] += 1
    stats["time_s"] += dt

    metrics = {}
    for line in out.splitlines():
        m = METRIC.match(line.strip())
        if m:
            metrics[m.group(1)] = float(m.group(2))
    missing = [k for k in ("gain_db", "ugf_hz", "pm_deg", "power_w") if k not in metrics]
    if crashed or missing:
        tail = crashed or "\n".join(l for l in out.splitlines() if "rror" in l or "fail" in l.lower())[-1500:]
        return {"ok": False, "metrics": metrics, "error": f"측정 누락={missing}\n{tail}", "sim_time_s": dt}
    if metrics["ugf_hz"] <= 10 or metrics["gain_db"] <= 0:
        # 대역폭은 bias 전류에 비례한다 (20uA: 22MHz, 1nA: 2.3kHz, 1pA: 7Hz). 1pA면 측정 범위(10Hz) 아래로 내려가고, 전류가 누설과 비슷해 동작점을 믿을 수 없다
        return {"ok": False, "metrics": metrics, "sim_time_s": dt,
                "error": f"측정 무효: gain(10Hz)={metrics['gain_db']:.1f}dB, UGF={metrics['ugf_hz']:.1f}Hz — 회로가 증폭기로 동작하지 않음 (바이어스 확인)"}
    return {"ok": True, "metrics": metrics, "error": None, "sim_time_s": dt}
