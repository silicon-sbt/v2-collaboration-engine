"""T12 tests: soft/hard budget thresholds, overspend responsibility (debt vs
loss), and per-persona reputation proxy (exposed, not gated).
"""

from __future__ import annotations

from pathlib import Path

from collab.costing import rep_by_persona
from collab.graph import build_collab_graph
from collab.models import Task

ROOT = Path(__file__).resolve().parent.parent


class CostCaptureLLM:
    provider_name = "openai"
    model = "gpt-4o-mini"
    last_usage = {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}

    def generate(self, prompt: str) -> str:
        return "采用方案A，理由：成本可控。"


def _run(llm, task: Task):
    app = build_collab_graph(llm, root_dir=ROOT)
    return app.invoke(
        {
            "tasks": [task.to_dict()],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
            "attempts": [],
        }
    )


def test_task_soft_budget_defaults_to_80percent():
    t = Task(id="t", persona_id="p", input="x", budget_tokens=1000)
    assert t.budget_soft_tokens == 800
    t2 = Task(id="t2", persona_id="p", input="x", budget_tokens=1000, budget_soft_tokens=500)
    assert t2.budget_soft_tokens == 500


def test_soft_budget_warns_but_completes():
    state = _run(CostCaptureLLM(), Task(id="t-001", persona_id="computing", input="估算成本",
                                        expected_output="方案", budget_tokens=1000, budget_soft_tokens=200))
    res = {r["id"]: r for r in state["results"]}
    assert res["t-001"]["status"] == "done"
    assert res["t-001"]["soft_budget_warning"] is True
    assert res["t-001"]["overspend_kind"] == "debt"
    assert "软上限预警任务数: 1" in state["final_report"]
    assert "超支责任: debt=1; loss=0" in state["final_report"]


def test_budget_exceeded_is_loss():
    state = _run(CostCaptureLLM(), Task(id="t-001", persona_id="computing", input="估算成本",
                                        expected_output="方案", budget_tokens=200, budget_soft_tokens=100))
    res = {r["id"]: r for r in state["results"]}
    assert res["t-001"]["status"] == "failed"
    assert res["t-001"]["failure_type"] == "budget_exceeded"
    assert res["t-001"]["overspend_kind"] == "loss"


def test_rep_by_persona():
    results = [
        {"id": "t1", "status": "done", "verdict": {"ok": True},
         "audit": {"persona_id": "computing", "cost_usd": 0.03}},
        {"id": "t2", "status": "failed", "failure_type": "budget_exceeded"},
    ]
    attempts = [
        {"id": "t1", "persona_id": "computing", "cost_usd": 0.04},
        {"id": "t2", "persona_id": "computing", "cost_usd": 0.02},
    ]
    rep = rep_by_persona(results, attempts)
    assert abs(rep["computing"] - (0.03 / 0.06)) < 1e-6


def test_rep_omitted_when_no_attempts():
    # A missing denominator must not read as a perfect reputation.
    results = [{"id": "t1", "status": "done", "verdict": {"ok": True},
                "audit": {"persona_id": "computing", "cost_usd": 0.03}}]
    rep = rep_by_persona(results, attempts=[])
    assert "computing" not in rep
