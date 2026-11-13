"""Agent 루프: 가짜 LLM으로 (API 호출 없음)"""
import json
from types import SimpleNamespace as NS

import httpx
from openai import APIError

from agent import agent
from eda import spec, spice

P = {k: spice.DEFAULT[k] for k in spec.BOUNDS}


def feasible():
    rows = json.load(open("eval/results/sample_space.json"))
    return next(r["params"] for r in rows if r["valid"] and r["gain_db"] >= 42 and r["power_w"] <= 70e-6
                and r["ugf_hz"] >= 20e6 and r["pm_deg"] >= 60 and r["margin_v"] >= 0.05)


class FakeLLM:
    """정해진 도구 호출을 순서대로 내는 가짜 LLM"""
    def __init__(self, calls):
        self.calls, self.chat = list(calls), self
        self.completions = self

    def create(self, **_):
        if isinstance(self.calls[0], Exception):
            raise self.calls.pop(0)
        name, args = self.calls.pop(0)
        tc = NS(id="c1", function=NS(name=name, arguments=json.dumps(args)))
        msg = NS(tool_calls=[tc], content=None,
                 model_dump=lambda **_: {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function",
                                          "function": {"name": name, "arguments": json.dumps(args)}}]})
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=5))


def test_stops_when_code_grading_passes():
    # 통과는 LLM 말이 아니라 채점 결과로: 해가 있는 설계를 평가하는 순간 끝난다 (그 뒤 호출은 쓰이지 않음)
    llm = FakeLLM([("evaluate_design", {"params": P}), ("evaluate_design", {"params": feasible()}),
                   ("evaluate_design", {"params": P})])
    r = agent.run(P, sim_budget=100, client=llm, guard=False)
    assert r["solved"] and r["sims"] == 30 and len(llm.calls) == 1


def test_bad_tool_args_and_api_error_do_not_crash():
    err = APIError("flagged", request=httpx.Request("POST", "http://x"), body=None)
    r = agent.run(P, sim_budget=100, client=FakeLLM([("evaluate_design", {"params": {"ibias": 1}}), err]))
    assert not r["solved"] and "API 오류" in r["reason"] and r["sims"] == 0
    assert "빠짐" in json.loads(r["messages"][3]["content"])["error"]  # 잘못된 인자는 이유와 함께 돌려준다


def test_guard_blocks_back_to_back_evaluate():
    calls = [("evaluate_design", {"params": P}), ("evaluate_design", {"params": P}),  # 두 번째는 거부 (시뮬레이션 0)
             ("inspect_operating_point", {"params": P, "corner": "tt", "temp": 27}),
             ("evaluate_design", {"params": feasible()})]  # 진단 뒤에는 허용
    r = agent.run(P, sim_budget=100, client=FakeLLM(calls))
    assert r["solved"] and r["sims"] == 31 and r["trace"]["guard_refusals"] == 1
    r = agent.run(P, sim_budget=100, client=FakeLLM(calls[:2] + [calls[3]]), guard=False)
    assert r["solved"] and r["sims"] == 45 and r["trace"]["guard_refusals"] == 0  # 끄면 그대로 실행 (ablation용)
