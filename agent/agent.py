"""EDA 사이징 Agent: 스펙을 받아 도구(시뮬레이션·동작점·sweep·최적화기)를 골라 쓰며 15개 조건을 맞춘다.

LLM이 하는 일: 실패 원인 해석(어느 조건, 어느 트랜지스터, 어느 동작 영역), 어떤 손잡이를 어느 도구로 움직일지 계획.
LLM에게 맡기지 않는 일: 숫자 미세 조정(local_search), 범위·예산 검사, 통과 판정(코드가 채점).
evaluate_design이나 local_search의 전체 검증이 통과하면 그 자리에서 끝낸다 (LLM 말이 아니라 채점 결과로).
"""

import json
import os
import sys
import time

from dotenv import load_dotenv
from openai import APIError, OpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from eda import spec, spice, tools  # noqa: E402

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
PRICE = {"gpt-5-mini": {"input": 0.25, "output": 2.00}}  # $/1M 토큰
MAX_STEPS = 40

KNOBS = {k: {"type": "number"} for k in spec.BOUNDS}
PARAMS_SCHEMA = {"type": "object", "properties": KNOBS, "required": list(KNOBS), "additionalProperties": False}
COND = {"type": "array", "items": {"type": "array", "items": [{"type": "string"}, {"type": "integer"}]}}
TOOLS = [
    {"type": "function", "function": {"name": "evaluate_design",
        "description": "15개 조건(5 corner x 3 온도) 전체 채점. 시뮬레이션 15회. 통과 여부, 조건별 부족분, 지표별 최악값과 그 위치",
        "parameters": {"type": "object", "properties": {"params": PARAMS_SCHEMA}, "required": ["params"]}}},
    {"type": "function", "function": {"name": "inspect_operating_point",
        "description": "한 조건에서 트랜지스터별 동작점: 영역(saturation/edge/triode), 포화 여유, 오버드라이브, gm/Id(약 20 이상이면 약반전), 전류, 고유 이득. 시뮬레이션 1회. 측정이 실패한 조건도 동작점은 볼 수 있다",
        "parameters": {"type": "object", "properties": {"params": PARAMS_SCHEMA, "corner": {"type": "string", "enum": spice.CORNERS},
                                                         "temp": {"type": "integer", "enum": spice.TEMPS}},
                       "required": ["params", "corner", "temp"]}}},
    {"type": "function", "function": {"name": "sweep_parameter",
        "description": "손잡이 하나를 2~8개 값으로 바꿔 가며 한 조건에서 gain/UGF/PM/전력/최소 포화 여유를 본다. 값 개수만큼 시뮬레이션. 경향을 싸게 확인할 때",
        "parameters": {"type": "object", "properties": {"params": PARAMS_SCHEMA, "name": {"type": "string", "enum": list(KNOBS)},
                                                         "values": {"type": "array", "items": {"type": "number"}},
                                                         "corner": {"type": "string", "enum": spice.CORNERS},
                                                         "temp": {"type": "integer", "enum": spice.TEMPS}},
                       "required": ["params", "name", "values", "corner", "temp"]}}},
    {"type": "function", "function": {"name": "local_search",
        "description": "최적화기: 고른 손잡이만 무작위로 조금씩 흔들어 나아지면 받아들인다(1+1 ES). conditions를 주면 그 조건들에서만 채점해 아끼고, 끝에 15개 조건 전체로 검증한다. 방향은 맞는데 숫자를 맞추기 어려울 때. 비용 = iterations x 조건 수 + 15",
        "parameters": {"type": "object", "properties": {"params": PARAMS_SCHEMA,
                                                         "knobs": {"type": "array", "items": {"type": "string", "enum": list(KNOBS)}},
                                                         "iterations": {"type": "integer"}, "step": {"type": "number"},
                                                         "conditions": COND},
                       "required": ["params", "knobs"]}}},
]

SYSTEM_PROMPT = f"""너는 아날로그 회로 설계자다. 5T OTA의 사이징을 맞춘다.

회로: NMOS 입력 차동쌍(m1, m2; w_in, l_in) + PMOS 전류 미러 부하(m3, m4; w_load, l_load)
      + NMOS tail 전류원(mt)과 bias 미러(mb)(둘 다 w_tail, l_tail). bias 전류 ibias를 tail이 복사한다.
      전원 1.8V, 입력 공통 전압 0.9V, 부하 1pF (이 셋은 고정). W/L 단위 um, ibias 단위 A.
스펙 (15개 조건 = corner tt ff ss sf fs x 온도 -40 27 125°C, 전부 만족해야 통과):
  gain_db >= {spec.SPEC['gain_db'][1]}, ugf_hz >= {spec.SPEC['ugf_hz'][1]:.0e}, pm_deg >= {spec.SPEC['pm_deg'][1]},
  power_w <= {spec.SPEC['power_w'][1]:.0e}, 모든 트랜지스터 포화 여유(|Vds| - Vdsat) >= 50mV
손잡이 범위: {json.dumps(spec.BOUNDS)}

일하는 방식
- 비용은 시뮬레이션 횟수다. 도구 결과에 남은 예산이 나온다. 낭비하지 마라.
- 먼저 evaluate_design으로 어디서 무엇이 부족한지 본다. 가장 나쁜 조건은 inspect_operating_point로
  원인을 진단한다(어느 트랜지스터가 포화를 벗어났나, 약반전인가 강반전인가). 진단 없이 숫자를 바꾸지 마라.
- 손잡이가 범위 끝에 닿았거나 바꿔도 효과가 없으면, 같은 방향을 반복하지 말고 다른 손잡이로 맞바꿀 방법을 찾는다.
  예: 약반전에서는 W를 키워도 gm이 거의 늘지 않는다.
- 경향을 모르면 sweep_parameter로 싸게 확인한다. 방향을 정한 뒤 숫자 미세 조정은 local_search에 맡긴다.
- 매번 손잡이 7개를 모두 준다. 통과하면 시스템이 자동으로 끝낸다.
"""


def call_tool(budget, name, args):
    fn = {"evaluate_design": tools.evaluate_design, "inspect_operating_point": tools.inspect_operating_point,
          "sweep_parameter": tools.sweep_parameter, "local_search": tools.local_search}.get(name)
    if fn is None:
        return {"error": f"모르는 도구: {name}"}
    try:
        return fn(budget, **args)
    except (TypeError, ValueError, KeyError) as e:  # 인자 형식이 틀린 호출 → 고쳐 부를 수 있게 이유를 돌려준다
        return {"error": f"도구 인자 오류: {e}"}


def passed_params(name, args, result):
    if name == "evaluate_design" and result.get("passed"):
        return args["params"]
    if name == "local_search" and result.get("full_check", {}).get("passed"):
        return result["best_params"]


GUARD_MSG = ("거부: 직전 evaluate_design이 실패했는데 진단 없이 다시 채점하려 한다. "
             "먼저 inspect_operating_point나 sweep_parameter로 원인을 확인하거나, 숫자 조정은 local_search에 맡겨라. (시뮬레이션은 쓰지 않았다)")


def guard_refuses(name, last):
    """1차 평가의 실패 패턴(진단 없이 evaluate를 연달아 부르며 손으로 숫자를 바꿈, 기록 8번)을 코드로 막는다.
    프롬프트에 "진단 없이 숫자를 바꾸지 마라"고 써도 지키지 않았다."""
    return name == "evaluate_design" and last is not None and last[0] == "evaluate_design" and not last[1]


HANDOFF_SCORE = 0.01  # 실패 19개를 오프라인으로 마무리해 보니 1% 이내는 8개 중 7개가 최적화기로 통과 (기록 10번)


def scored(name, args, out):
    """도구 결과에서 15개 조건 전체 점수와 그 설계를 꺼낸다 (없으면 None)"""
    if name == "evaluate_design" and out.get("score") is not None:
        return out["score"], args["params"]
    if name == "local_search" and out.get("full_check", {}).get("score") is not None:
        return out["full_check"]["score"], out["best_params"]


def run(start_params, sim_budget=2000, client=None, guard=True, handoff=True):
    client = client or OpenAI()
    budget = tools.Budget(sim_budget)
    start = {k: float(f"{start_params[k]:.4g}") for k in spec.BOUNDS}
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"시작 설계: {json.dumps(start)}. 시뮬레이션 예산 {sim_budget}회 안에 스펙을 맞춰라."}]
    trace = {"steps": [], "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "guard_refusals": 0, "handoffs": []}
    handoff_floor = float("inf")  # 마무리를 시도한 점수보다 더 좋아졌을 때만 다시 시도
    last = None  # (도구 이름, 통과했나)
    t0 = time.time()
    result = {"solved": False, "reason": "단계 한도"}
    for _ in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        except APIError as e:  # 예: 프롬프트가 사용 정책 위반으로 오판돼 400 (평가 중 실제로 한 번). 평가 전체가 죽지 않게 이 실행의 실패로 기록
            result = {"solved": False, "reason": f"API 오류: {str(e)[:200]}"}
            break
        trace["llm_calls"] += 1
        trace["input_tokens"] += resp.usage.prompt_tokens
        trace["output_tokens"] += resp.usage.completion_tokens
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            result = {"solved": False, "reason": "Agent가 도구 없이 끝냄: " + (msg.content or "")[:300]}
            break
        done, near = None, None
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                args, out = {}, {"error": "인자가 JSON이 아니다"}
            else:
                if guard and guard_refuses(call.function.name, last):
                    out = {"error": GUARD_MSG}
                    trace["guard_refusals"] += 1
                else:
                    out = call_tool(budget, call.function.name, args)
                    last = (call.function.name, bool(out.get("passed")))
            out["budget_left"] = sim_budget - budget.used
            trace["steps"].append({"tool": call.function.name, "args": {k: v for k, v in args.items() if k != "params"},
                                   "sims_used": budget.used, "error": out.get("error"),
                                   "passed": out.get("passed", out.get("full_check", {}).get("passed"))})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(out, ensure_ascii=False)})
            done = done or passed_params(call.function.name, args, out)
            sc = scored(call.function.name, args, out)
            if sc and 0 < sc[0] <= HANDOFF_SCORE and sc[0] < handoff_floor and (near is None or sc[0] < near[0]):
                near = sc
        if not done and near and handoff:
            # 거의 통과: 마지막 미세 조정은 LLM이 아니라 최적화기가 15개 조건 전부로 채점하며 한다
            iters = min(60, (sim_budget - budget.used) // len(spec.ALL_POINTS) - 1)
            if iters >= 1:
                ls = tools.local_search(budget, near[1], list(spec.BOUNDS), iterations=iters, step=0.05)
                fc = ls.get("full_check", {})
                trace["handoffs"].append({"from": near[0], "to": fc.get("score"), "sims_used": budget.used})
                handoff_floor = fc.get("score") if fc.get("score") is not None else near[0]
                if fc.get("passed"):
                    done = ls["best_params"]
                else:
                    messages.append({"role": "user", "content": "시스템이 거의 통과한 설계를 최적화기(15개 조건 전체 채점)로 마무리하려 했지만 통과하지 못했다. "
                                     + json.dumps({"best_params": ls.get("best_params"), "result": fc, "budget_left": sim_budget - budget.used}, ensure_ascii=False)})
        if done:
            result = {"solved": True, "params": done}
            break
        if budget.used >= sim_budget - 1:
            result = {"solved": False, "reason": "예산 소진"}
            break
    price = PRICE.get(MODEL, {"input": 0, "output": 0})
    trace["cost_usd"] = round((trace["input_tokens"] * price["input"] + trace["output_tokens"] * price["output"]) / 1e6, 4)
    trace["latency_s"] = round(time.time() - t0, 1)
    return {**result, "sims": budget.used, "trace": trace, "messages": messages}


if __name__ == "__main__":
    r = run({k: spice.DEFAULT[k] for k in spec.BOUNDS})
    print(json.dumps({k: v for k, v in r.items() if k != "messages"}, ensure_ascii=False, indent=1))
