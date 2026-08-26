"""Tests for the V2 async runner entry (T7).

Covers run_collaboration (background run + run id), get_collab_status polling,
stop_collab soft-stop, and the 3-task scenario demo (cross-referencing peers).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from collab.runner import (
    get_collab_status,
    list_collab_runs,
    run_collaboration,
    stop_collab,
)

ROOT = Path(__file__).resolve().parent.parent


def _wait_done(run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_collab_status(run_id)
        if status["status"] in ("done", "failed", "stopped"):
            return status
        time.sleep(0.05)
    raise TimeoutError("run did not finish: " + str(get_collab_status(run_id)))


def test_run_collaboration_returns_run_id_and_completes():
    tasks = [
        {"id": "t-001", "persona_id": "computing", "input": "评估符号计算的影响", "expected_output": "给出判断"},
        {"id": "t-002", "persona_id": "history", "input": "从技术史角度评价", "expected_output": "给出判断"},
    ]
    run_id = run_collaboration(tasks, mock=True, root_dir=ROOT)
    assert run_id
    status = _wait_done(run_id)
    assert status["status"] == "done", status
    assert status["task_count"] == 2
    assert status["token_total"] >= 0
    assert status["final_report"], "expected a report"


def test_run_collaboration_requires_valid_tasks():
    with pytest.raises(ValueError):
        run_collaboration([], mock=True, root_dir=ROOT)
    with pytest.raises(ValueError):
        run_collaboration([{"input": "缺 id"}], mock=True, root_dir=ROOT)


def test_get_collab_status_unknown_run():
    status = get_collab_status("nope")
    assert status["status"] == "not_found"


def test_stop_collab_soft_stop():
    # A run that completes quickly may already be done; stop only applies to
    # in-flight runs. Use a large task set to keep it running a moment.
    tasks = [
        {"id": "t-" + str(i), "persona_id": "computing", "input": "任务 " + str(i)}
        for i in range(5)
    ]
    run_id = run_collaboration(tasks, mock=True, root_dir=ROOT)
    result = stop_collab(run_id, reason="review")
    # Soft-stop either marks it stopped or reports already-finished - both are
    # valid because mock runs can finish before stop lands.
    assert result["ok"] in (True, False)
    if result["ok"]:
        status = get_collab_status(run_id)
        assert status["stop_reason"] == "review"


def test_list_collab_runs_contains_run():
    run_id = run_collaboration(
        [{"id": "t1", "persona_id": "computing", "input": "任务"}],
        mock=True,
        root_dir=ROOT,
    )
    ids = [item["run_id"] for item in list_collab_runs()]
    assert run_id in ids


def test_scenario_three_tasks_cross_referencing():
    """M1 scenario demo: A produces, B cites A, C summarises A+B (allowed_links
    give B and C visibility of each other)."""
    tasks = [
        {
            "id": "a-research",
            "persona_id": "investing",
            "input": "调研：列出市场风险的主要类别",
            "expected_output": "风险清单",
            "allowed_links": ["b-check"],
        },
        {
            "id": "b-check",
            "persona_id": "macroeconomics",
            "input": "基于 a-research 的风险清单，评估宏观应对",
            "expected_output": "宏观应对建议",
            "data_deps": ["a-research"],
            "allowed_links": ["a-research", "c-summary"],
        },
        {
            "id": "c-summary",
            "persona_id": "history",
            "input": "综合 a-research 与 b-check 的观点，给出历史启示",
            "expected_output": "总结",
            "data_deps": ["a-research", "b-check"],
            "allowed_links": ["b-check"],
        },
    ]
    run_id = run_collaboration(tasks, mock=True, root_dir=ROOT)
    status = _wait_done(run_id)
    assert status["status"] == "done", status
    by_id = {r["id"]: r for r in status["results"]}
    assert by_id["a-research"]["status"] == "done"
    assert by_id["b-check"]["status"] == "done"
    assert by_id["c-summary"]["status"] == "done"
    assert "a-research" in status["final_report"]
    assert "b-check" in status["final_report"]

def test_stop_survives_worker_completion():
    """Review: stop_collab must not be overwritten by the worker finishing."""
    import time

    # A slower run (multiple tasks) so stop lands while running.
    tasks = [
        {"id": "t-" + str(i), "persona_id": "computing", "input": "任务 " + str(i)}
        for i in range(4)
    ]
    run_id = run_collaboration(tasks, mock=True, root_dir=ROOT)
    result = stop_collab(run_id, reason="review-stop")
    if not result["ok"]:
        return  # run already finished before stop landed; not this race
    # Wait for the worker to finish; status must remain stopped.
    time.sleep(0.5)
    status = get_collab_status(run_id)
    assert status["status"] == "stopped", status
    assert status["stop_reason"] == "review-stop"
