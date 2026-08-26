"""T14 tests: execution mode (wave / parallel) resolution and experimental marking.
"""

from __future__ import annotations

import pytest

from collab.graph import resolve_mode, run_collab_sync
from collab.models import Task


def _task(task_id: str, persona: str, input_text: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id=persona, input=input_text, **kwargs)


def test_resolve_mode_wave_default():
    assert resolve_mode([], "wave") == ("wave", False, "")


def test_resolve_mode_parallel_no_deps_experimental():
    tasks = [{"id": "t1", "data_deps": []}, {"id": "t2", "data_deps": []}]
    assert resolve_mode(tasks, "parallel") == ("parallel", True, "")


def test_resolve_mode_parallel_with_deps_falls_back():
    tasks = [{"id": "t1", "data_deps": []}, {"id": "t2", "data_deps": ["t1"]}]
    mode, experimental, note = resolve_mode(tasks, "parallel")
    assert mode == "wave"
    assert experimental is False
    assert "no data_deps" in note


def test_resolve_mode_invalid_raises():
    with pytest.raises(ValueError):
        resolve_mode([], "mesh")


def test_resolve_mode_defaults_to_wave():
    # mode omitted -> wave (the roundtable default), not vacuous parallel.
    assert resolve_mode([{"id": "t1", "data_deps": []}]) == ("wave", False, "")


def test_resolve_mode_empty_tasks_parallel_falls_back():
    assert resolve_mode([], "parallel") == ("wave", False, "parallel requires no data_deps; fell back to wave")


def test_run_sync_parallel_marks_experimental():
    tasks = [_task("t1", "computing", "调研A"), _task("t2", "history", "调研B")]
    state = run_collab_sync(tasks, mode="parallel", mock=True)
    assert "模式: parallel（experimental）" in state["final_report"]
    assert state["mode"] == "parallel"
    assert state["experimental"] is True
    assert state["parallel_note"] == ""


def test_run_sync_parallel_with_deps_falls_back():
    tasks = [_task("t1", "computing", "调研A"), _task("t2", "history", "调研B", data_deps=["t1"])]
    state = run_collab_sync(tasks, mode="parallel", mock=True)
    assert "模式: wave" in state["final_report"]
    assert "parallel requires no data_deps" in state["final_report"]
    assert state["mode"] == "wave"
    assert state["experimental"] is False
    assert "no data_deps" in state["parallel_note"]
