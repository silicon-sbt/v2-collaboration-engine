"""Tests for V2 failure recovery and budget capping (T6).

Covers: retry-once semantics for recoverable failures (transient / manager
revise), no-retry for hard failures (audit_invalid/conflict/budget), per-task
token budget, and the global token budget stop.
"""

from __future__ import annotations

from pathlib import Path

from collab.graph import GLOBAL_TOKEN_BUDGET, build_collab_graph
from collab.models import Task, TaskStatus

ROOT = Path(__file__).resolve().parent.parent


def _task(task_id: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id="computing", input="任务", **kwargs)


class _FlakyLlm:
    """Fails the first N calls, then succeeds."""

    provider_name = "flaky"
    model = "flaky"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def __init__(self, fail_count: int = 1) -> None:
        self.fail_count = fail_count
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.calls <= self.fail_count:
            raise RuntimeError("transient outage")
        return "恢复后的产出"


def test_transient_failure_retries_once_then_succeeds():
    llm = _FlakyLlm(fail_count=1)
    tasks = [_task("t1")]
    app = build_collab_graph(llm, root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.DONE.value, result
    assert llm.calls == 2, "expected exactly one retry"
    assert state["final_report"]


def test_transient_failure_retry_exhausted_stays_failed():
    llm = _FlakyLlm(fail_count=99)
    tasks = [_task("t1")]
    app = build_collab_graph(llm, root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.FAILED.value, result
    # one original attempt + one retry = 2 LLM calls max.
    assert llm.calls == 2, llm.calls


class _ReviseThenPassLlm:
    """First arbitration call says REVISE, retried execution then manager passes."""

    provider_name = "rp"
    model = "rp"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: str) -> str:
        if "COLLAB_MANAGER_ARBITRATION" in prompt:
            self.calls += 1
            return "REVISE" + chr(10) + "第一次不达标" if self.calls == 1 else "PASS" + chr(10) + "第二次达标"
        return "任务产出内容"


def test_manager_revise_retries_once_then_passes():
    llm = _ReviseThenPassLlm()
    tasks = [_task("t1", expected_output="要给出量化结论")]
    app = build_collab_graph(llm, root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.DONE.value, result
    assert result.get("verdict", {}).get("ok") is True, result


def test_task_token_budget_exceeded_fails_no_retry():
    """A task that blows its per-task budget fails with budget_exceeded (no retry)."""

    class _SpendyLlm:
        provider_name = "spendy"
        model = "spendy"
        last_usage = {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}

        def generate(self, prompt: str) -> str:
            return "产出"

    tasks = [_task("t1", budget_tokens=10)]  # single call uses 20 tokens > 10
    app = build_collab_graph(_SpendyLlm(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.FAILED.value, result
    assert result.get("failure_type") == "budget_exceeded", result


def test_global_budget_stops_later_wave_tasks():
    """Global budget caps are enforced at wave boundaries (M1 semantics): tasks
    in the SAME wave run in parallel and cannot be interrupted mid-flight, but
    any later wave is stopped once the accumulated total passes the cap."""

    class _SpendyLlm:
        provider_name = "spendy"
        model = "spendy"
        last_usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

        def generate(self, prompt: str) -> str:
            return "产出"

    import collab.graph as graph_mod

    original = graph_mod.GLOBAL_TOKEN_BUDGET
    graph_mod.GLOBAL_TOKEN_BUDGET = 150  # wave 1 (t1) already spends 200 > 150
    try:
        # t2 depends on t1, so it runs in a later wave where the cap is checked.
        tasks = [_task("t1"), _task("t2", data_deps=["t1"])]
        app = build_collab_graph(_SpendyLlm(), root_dir=ROOT)
        state = app.invoke({
            "tasks": [t.to_dict() for t in tasks],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
        })
    finally:
        graph_mod.GLOBAL_TOKEN_BUDGET = original
    by_id = {r["id"]: r for r in state["results"]}
    assert by_id["t1"]["status"] == TaskStatus.DONE.value, by_id
    assert by_id["t2"]["status"] == TaskStatus.STOPPED.value, by_id
    assert by_id["t2"].get("failure_type") == "global_budget", by_id
    assert state["final_report"]
