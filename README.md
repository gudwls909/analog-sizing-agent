# EDA Design Optimization Agent

자연어 설계 목표 → EDA 도구 실행 → 결과 분석 → 최적화 → 검증을 Agent가 orchestration한다.
첫 대상: SKY130 공개 PDK의 5T OTA, 고정 topology에서 W/L·bias 전류만 바꾼다.

> 진행 중.

## 설치

```bash
conda create -n eda-agent -c conda-forge python=3.11 ngspice pytest
pip install volare
volare enable --pdk sky130 --pdk-root ~/pdk -l sky130_fd_pr c6d73a35f524070e85faff4a6a9eef49553ebc2b   # 소자 모델만, 216MB
pytest   # 실제 ngspice 실행, 약 1분 (대부분 세션 첫 로딩)
```

## 기준 회로 (5T OTA, 기본 사이징)

| corner \ 온도 | -40°C | 27°C | 125°C |
|---|---|---|---|
| tt | 36.7dB / 25.1MHz | **36.5dB / 22.1MHz / PM 89.5° / 67µW** | 36.1dB / 18.7MHz |
| ss | 37.1dB / 23.2MHz | 36.9dB / 20.5MHz | 36.4dB / 17.4MHz |
| ff | 36.3dB / 26.6MHz | 36.1dB / 23.4MHz | 35.6dB / 19.8MHz |

5 corner × 3 온도. (corner, 온도)마다 ngspice 세션을 띄워 두고 파라미터만 바꿔 다시 계산: 1회 0.05초, 15개 조건 전체 0.16초 (첫 로딩 18초).

## 구성

- [x] `eda/spice.py`: 상주 ngspice 세션 → 측정값 추출, 호출 횟수·시간 기록, 실패·무효 측정 보고
- [x] `eda/analysis.py`: 트랜지스터별 포화 여유(|Vds| − Vdsat), tail 미러 전류 비율, 고유 이득(gm/gds) → "스펙은 맞는데 회로가 건강하지 않음"을 판정. 기본 사이징의 tail이 15개 구간 전부 선형 영역임을 발견 ([기록 3번](docs/troubleshooting_log.md))
- [x] `eda/spec.py`: 스펙(gain ≥ 42dB, UGF ≥ 20MHz, PM ≥ 60°, 전력 ≤ 70µW, 포화 여유 ≥ 50mV, 15개 조건 전부), 손잡이 범위, 채점(최악 조건의 부족분 합). 난이도는 무작위 설계 3000개로 보정 ([기록 6번](docs/troubleshooting_log.md))
- [x] `baselines/random_search.py`: 2000회 예산으로 **2/10 해결** (494, 1497회). 실패한 8개도 TT는 통과한 후보를 찾음 → 어려운 건 corner (이전 스펙은 10/10, 중앙값 295회)
- [x] `baselines/rule_based.py`: 교과서 규칙. 기본값 시작은 300회로 해결, 무작위 시작은 2/10 — 막힌 6개 전부 손잡이가 범위 끝에 붙음 ([기록 7번](docs/troubleshooting_log.md))
- [x] `agent/agent.py` + `eda/tools.py`: 도구 4개(채점, 동작점, sweep, local_search). 범위·예산·통과 판정은 코드. 무작위 시작 **8/10 해결**(규칙 2/10, random search 2/10), 실패는 전부 LLM 단계 한도 ([기록 8번](docs/troubleshooting_log.md))
- [x] 시작점 11개 × 3회 반복: Agent **24/33 해결**. "진단 없이 숫자 바꾸기" 금지(guard)는 효과 없음(차이 −0.03, CI [−0.15, +0.09]). 실패 대부분이 2% 이내로 거의 통과한 채 LLM 단계 한도 ([기록 9번](docs/troubleshooting_log.md))
- [ ] 마지막 미세 조정 개선 (거의 통과하면 최적화기로 넘기기)
- [ ] 최적화기 연결 (random search, 규칙 기반 → BO)
- [ ] corner 검증, 베이스라인 비교 (LLM 단독 / 최적화기 단독 / hybrid)
