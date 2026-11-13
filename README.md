# EDA Design Optimization Agent

자연어 설계 목표 → EDA 도구 실행 → 결과 분석 → 최적화 → 검증을 Agent가 orchestration한다.
첫 대상: SKY130 공개 PDK의 5T OTA, 고정 topology에서 W/L·bias 전류만 바꾼다.

> 진행 중. 지금은 1단계(공개 PDK + ngspice + Python 실행·측정).

## 설치

```bash
conda create -n eda-agent -c conda-forge python=3.11 ngspice pytest
pip install volare
volare enable --pdk sky130 --pdk-root ~/pdk -l sky130_fd_pr c6d73a35f524070e85faff4a6a9eef49553ebc2b   # 소자 모델만, 216MB
pytest   # 실제 ngspice 실행, 약 30초
```

## 기준 회로 (5T OTA, 기본 사이징)

| corner \ 온도 | -40°C | 27°C | 125°C |
|---|---|---|---|
| tt | 36.7dB / 25.1MHz | **36.5dB / 22.1MHz / PM 89.5° / 67µW** | 36.1dB / 18.7MHz |
| ss | 37.1dB / 23.2MHz | 36.9dB / 20.5MHz | 36.4dB / 17.4MHz |
| ff | 36.3dB / 26.6MHz | 36.1dB / 23.4MHz | 35.6dB / 19.8MHz |

5 corner × 3 온도 15회, 8개 병렬. 시뮬레이션 1회 약 12초(대부분 모델 로딩).

## 구성

- [x] `eda/spice.py`: 넷리스트 채우기 → ngspice 실행 → 측정값 추출, 호출 횟수·시간 기록, 실패·무효 측정 보고
- [ ] 측정·동작점(saturation) 분석 도구
- [ ] Agent: 도구 선택과 실행 계획
- [ ] 최적화기 연결 (random search, 규칙 기반 → BO)
- [ ] corner 검증, 베이스라인 비교 (LLM 단독 / 최적화기 단독 / hybrid)
