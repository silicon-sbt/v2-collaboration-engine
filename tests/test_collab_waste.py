"""T11 tests: waste attribution (effective vs discarded), feedback/compliance
metrics, and per-execution attempt recording in the graph.
"""

from __future__ import annotations

from pathlib import Path

from collab.costing import feedback_summary, waste_breakdown
from collab.graph import build_collab_graph
from collab.models import Task

ROOT = Path(__file__).resolve().parent.parent


class CostCaptureLLM:
    provider_name = "openai"
    model = "gpt-4o-mini"
    last_usage = {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}

    def generate(self, prompt: str) -> str:
        return "采用方案A，理由：成本可控。"


def _task(task_id: str, persona: str, input_text: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id=persona, input=input_text, **kwargs)


def test_waste_breakdown_splits_effective_vs_waste():
    results = [
        {"id": "t1", "status": "done", "verdict": {"ok": True},
         "audit": {"persona_id": "computing", "token_usage": 100, "cost_usd": 0.02}},
        {"id": "t2", "status": "failed", "failure_type": "manager_revise"},
    ]
    attempts = [
        {"id": "t1", "failure_type": "", "token_usage": 100, "cost_usd": 0.02},
        {"id": "t2", "failure_type": "transient", "token_usage": 50, "cost_usd": 0.01},
        {"id": "t2", "failure_type": "", "token_usage": 80, "cost_usd": 0.02},
    ]
    w = waste_breakdown(results, attempts)
    assert w["effective_cost_usd"] == 0.02
    assert abs(w["total_cost_usd"] - 0.05) < 1e-6
    assert abs(w["waste_cost_usd"] - 0.03) < 1e-6
    assert w["waste_tokens"] == 130  # 230 - 100
    reasons = {(r["id"], r["failure_type"]) for r in w["waste_reasons"]}
    assert ("t2", "transient") in reasons
    assert ("t2", "manager_revise") in reasons


def test_feedback_summary_compliance():
    attempts = [
        {"id": "t1", "failure_type": "transient"},
        {"id": "t2", "failure_type": "transient"},
    ]
    results = [
        {"id": "t1", "status": "done", "verdict": {"ok": True}},
        {"id": "t2", "status": "failed", "failure_type": "manager_revise"},
    ]
    fb = feedback_summary(attempts, results)
    assert fb["tasks_that_retried"] == 2
    assert fb["retries_that_succeeded"] == 1
    assert abs(fb["recovery_rate"] - 0.5) < 1e-9


def test_feedback_summary_catches_revise_retry():
    # A task executed twice (revised then retried) must count as "needed a retry".
    attempts = [
        {"id": "t1", "failure_type": "", "token_usage": 100, "cost_usd": 0.02, "attempt": 1},
        {"id": "t1", "failure_type": "", "token_usage": 90, "cost_usd": 0.02, "attempt": 2},
    ]
    results = [{"id": "t1", "status": "done", "verdict": {"ok": True}}]
    fb = feedback_summary(attempts, results)
    assert fb["tasks_that_retried"] == 1
    assert fb["retries_that_succeeded"] == 1
    assert abs(fb["recovery_rate"] - 1.0) < 1e-9


def test_waste_breakdown_marks_superseded_attempt():
    results = [{"id": "t1", "status": "done", "verdict": {"ok": True},
                "audit": {"token_usage": 100, "cost_usd": 0.02}}]
    attempts = [
        {"id": "t1", "attempt": 1, "failure_type": "", "token_usage": 80, "cost_usd": 0.02},
        {"id": "t1", "attempt": 2, "failure_type": "", "token_usage": 100, "cost_usd": 0.02},
    ]
    w = waste_breakdown(results, attempts)
    assert abs(w["waste_cost_usd"] - 0.02) < 1e-6  # attempt 1 superseded by attempt 2
    reasons = {(r["id"], r["failure_type"]) for r in w["waste_reasons"]}
    assert ("t1", "superseded") in reasons


def test_recovery_rate_none_when_no_retries():
    attempts = [{"id": "t1", "attempt": 1, "failure_type": ""}]
    results = [{"id": "t1", "status": "done", "verdict": {"ok": True}}]
    fb = feedback_summary(attempts, results)
    assert fb["tasks_that_retried"] == 0
    assert fb["recovery_rate"] is None


def test_executor_records_attempts_in_state():
    llm = CostCaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT)
    task = _task("t-001", "computing", "估算方案成本", expected_output="给出方案")
    state = app.invoke(
        {
            "tasks": [task.to_dict()],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
            "attempts": [],
        }
    )
    assert state["attempts"], "executor should record at least one attempt"
    att = state["attempts"][0]
    assert att["id"] == "t-001"
    assert att["status"] == "done"
    assert att["failure_type"] == ""
    assert att["cost_usd"] > 0
    assert "成本(USD)" in state["final_report"]
