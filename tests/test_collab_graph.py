"""Tests for the V2 collaboration executor (T3): task dispatch, parallel
execution, data-dependency citation, L2 audit wiring, and the report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from collab.graph import build_collab_graph, run_collab_sync
from collab.models import Task, TaskStatus

ROOT = Path(__file__).resolve().parent.parent


def _task(task_id: str, persona: str, input_text: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id=persona, input=input_text, **kwargs)


def test_run_collab_sync_two_tasks_parallel_mock():
    tasks = [
        _task("t-001", "computing", "评估符号计算对传统数值计算的影响"),
        _task("t-002", "history", "从技术史角度评价计算工具演变"),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    results = {r["id"]: r for r in state["results"]}
    assert results["t-001"]["status"] == TaskStatus.DONE.value
    assert results["t-002"]["status"] == TaskStatus.DONE.value
    assert "audit" in results["t-001"]
    assert results["t-001"]["audit"]["token_usage"] >= 0
    assert state["final_report"]
    assert "t-001" in state["final_report"]


def test_data_dependency_citation():
    tasks = [
        _task("t-001", "investing", "列出资本市场的主要风险因素"),
        _task(
            "t-002",
            "macroeconomics",
            "基于 t-001 的风险清单，讨论宏观对策",
            data_deps=["t-001"],
        ),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    results = {r["id"]: r for r in state["results"]}
    assert results["t-001"]["status"] == TaskStatus.DONE.value
    assert results["t-002"]["status"] == TaskStatus.DONE.value
    # t-002 audit must cite the dependency snapshot in its summary.
    summary = results["t-002"]["audit"]["output_summary"]
    assert "引用输入快照" in summary
    assert "关键决策点" in summary
    assert "任务结论" in summary


def test_token_total_accumulates():
    tasks = [
        _task("t-001", "computing", "任务A"),
        _task("t-002", "history", "任务B"),
        _task("t-003", "philosophy", "任务C"),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    # Mock LLM has no usage -> total stays 0 (objective, never negative).
    assert state["token_total"] == 0


def test_failed_task_does_not_break_run():
    class ExplodingLLM:
        provider_name = "explode"
        model = "boom"

        def generate(self, prompt: str) -> str:
            raise RuntimeError("simulated provider outage")

    tasks = [_task("t-001", "computing", "任务A"), _task("t-002", "history", "任务B")]
    app = build_collab_graph(ExplodingLLM(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    results = {r["id"]: r for r in state["results"]}
    assert results["t-001"]["status"] == TaskStatus.FAILED.value
    assert results["t-002"]["status"] == TaskStatus.FAILED.value
    assert state["errors"], "expected collected errors"
    # collect still produces a report listing failures.
    assert state["final_report"]
    assert "failed" in state["final_report"]


def test_run_collab_sync_requires_tasks():
    with pytest.raises(ValueError):
        run_collab_sync([], mock=True, root_dir=ROOT)


def test_build_collab_graph_mock_personas_ok():
    # Real personas resolve from config; unknown persona id falls back gracefully.
    tasks = [_task("t-x1", "nonexistent_persona", "hello")]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    assert state["results"][0]["status"] == TaskStatus.DONE.value

def test_circular_dependency_blocks_without_deadlock():
    """A cyclic data dependency must not hang: tasks get BLOCKED instead."""
    tasks = [
        _task("t-a", "computing", "A", data_deps=["t-b"]),
        _task("t-b", "history", "B", data_deps=["t-a"]),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    results = {r["id"]: r for r in state["results"]}
    assert results["t-a"]["status"] == TaskStatus.BLOCKED.value
    assert results["t-b"]["status"] == TaskStatus.BLOCKED.value
    assert state["errors"], "expected deadlock errors"
    assert state["final_report"]


def test_wave_order_dependency_runs_after_dep():
    """data_deps task must execute only after its dependency produced an audit.
    (Regression: parallel fan-out used to race the dependency.)
    """
    tasks = [
        _task("t-001", "computing", "产出基准结论"),
        _task("t-002", "history", "引用 t-001 并给出补充", data_deps=["t-001"]),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    results = {r["id"]: r for r in state["results"]}
    assert results["t-002"]["audit"]["output_summary"]
    assert "引用输入快照" in results["t-002"]["audit"]["output_summary"]
    assert results["t-002"]["audit"]["output_summary"] != "N/A", "must cite dependency"

def test_blocked_reachability_no_false_positive_on_cycle():
    """A cyclic dependency yields BLOCKED with NO discrepancy (closure has no DONE)."""
    tasks = [
        _task("t-a", "computing", "A", data_deps=["t-b"]),
        _task("t-b", "history", "B", data_deps=["t-c"]),
        _task("t-c", "philosophy", "C", data_deps=["t-a"]),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    assert all(r["status"] == TaskStatus.BLOCKED.value for r in state["results"])
    assert not any("BLOCKED discrepancy" in e for e in state["errors"]), state["errors"]
    assert "BLOCKED 复核异常" not in state["final_report"]


def test_blocked_reachability_catches_mislabelled_blocked():
    """A task blocked despite a reachable DONE dependency must be flagged."""
    from collab.graph import build_collab_graph, _verify_blocked_reachability

    tasks = [
        _task("t-done", "computing", "完成的任务", data_deps=[]),
        _task("t-x", "history", "依赖已完成任务却仍被标记阻塞", data_deps=["t-done"]),
    ]
    # Hand-craft the state: t-done succeeded, t-x mislabelled BLOCKED.
    llm = _FakeLlm("ok")
    app = build_collab_graph(llm, root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [
            {"id": "t-done", "status": TaskStatus.DONE.value, "audit": {"output_summary": "x"}},
            {"id": "t-x", "status": TaskStatus.BLOCKED.value, "error": "dependency never terminal: t-done"},
        ],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    # The reachability helper must flag it: DONE dep reachable from BLOCKED.
    assert state["final_report"]
    assert any("BLOCKED discrepancy" in e for e in state["errors"]), state["errors"]


class _FakeLlm:
    """Minimal LLM stub for graph tests needing a real provider object."""

    provider_name = "fake"
    model = "fake"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def __init__(self, text: str = "ok") -> None:
        self.text = text

    def generate(self, prompt: str) -> str:
        return self.text

def test_horizontal_message_delivered_to_allowed_links():
    """T4: a completed task delivers its summary to peers in allowed_links,
    and the peer receives it as context in a later wave.
    """
    from collab.graph import build_collab_graph

    captured: dict[str, str] = {}

    class CaptureLlm:
        provider_name = "capture"
        model = "capture"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def generate(self, prompt: str) -> str:
            captured["last_prompt"] = prompt
            return "产出内容"

    tasks = [
        _task("t-a", "computing", "任务A", allowed_links=["t-b"]),
        _task("t-b", "history", "任务B：请回应协作伙伴的观点", data_deps=["t-a"], allowed_links=["t-a"]),
    ]
    app = build_collab_graph(CaptureLlm(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    messages = state.get("messages", [])
    assert messages, "expected horizontal messages"
    a_msg = next(m for m in messages if m["task_id"] == "t-a")
    assert "t-b" in a_msg["receivers"], a_msg
    assert "协作伙伴的消息" in captured.get("last_prompt", ""), captured


def test_allowed_links_gate_delivery():
    """T4: a task NOT in allowed_links must not receive the peer message."""
    from collab.graph import build_collab_graph

    seen_prompts: list[str] = []

    class CaptureLlm:
        provider_name = "capture2"
        model = "capture2"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def generate(self, prompt: str) -> str:
            seen_prompts.append(prompt)
            return "回应内容"

    tasks = [
        _task("t-a", "computing", "任务A", allowed_links=["t-b"]),
        _task("t-b", "history", "任务B", data_deps=["t-a"], allowed_links=["t-a"]),
        _task("t-c", "philosophy", "任务C", data_deps=["t-a"]),
    ]
    app = build_collab_graph(CaptureLlm(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    assert all(r["status"] == TaskStatus.DONE.value for r in state["results"])
    a_msg = next(m for m in state["messages"] if m["task_id"] == "t-a")
    assert a_msg["receivers"] == ["t-b"], a_msg
    # t-c prompt must not carry the collaboration section (not in allowed_links).
    t_c_prompt = next(p for p in seen_prompts if "任务C" in p)
    assert "协作伙伴的消息" not in t_c_prompt

def test_cross_cycle_dependency_blocks_outside_task():
    """T4 review: a task outside a cycle depending on a node inside it (E->B,
    B in cycle A->B->C->A) must also BLOCK without false discrepancy.
    """
    tasks = [
        _task("t-a", "computing", "A", data_deps=["t-b"]),
        _task("t-b", "history", "B", data_deps=["t-c"]),
        _task("t-c", "philosophy", "C", data_deps=["t-a"]),
        _task("t-e", "investing", "E", data_deps=["t-b"]),
    ]
    state = run_collab_sync(tasks, mock=True, root_dir=ROOT)
    results = {r["id"]: r for r in state["results"]}
    assert results["t-a"]["status"] == TaskStatus.BLOCKED.value
    assert results["t-b"]["status"] == TaskStatus.BLOCKED.value
    assert results["t-c"]["status"] == TaskStatus.BLOCKED.value
    # E depends on B (in the cycle) -> dependency can never be terminal -> BLOCK.
    assert results["t-e"]["status"] == TaskStatus.BLOCKED.value, results["t-e"]
    # No false discrepancy: the closure of E contains no DONE node.
    assert not any("BLOCKED discrepancy" in e for e in state["errors"]), state["errors"]
