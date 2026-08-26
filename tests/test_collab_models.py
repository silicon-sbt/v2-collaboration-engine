"""Tests for the V2 collaboration engine: task model + state machine (T1)."""

from __future__ import annotations

import pytest

from collab.models import CollabMessage, Task, TaskAudit, TaskStatus
from collab.state_machine import TaskStateMachine, can_transition, legal_targets


def _make_task(**overrides) -> Task:
    defaults = dict(
        id="t-001",
        persona_id="macroeconomics",
        input="分析债务风险",
        expected_output="风险评估报告",
    )
    defaults.update(overrides)
    return Task(**defaults)


def test_task_defaults():
    task = _make_task()
    assert task.status == TaskStatus.PENDING
    assert task.budget_tokens == 80_000
    assert task.data_deps == []
    assert task.allowed_links == []
    assert task.audit is None


def test_task_validation():
    with pytest.raises(ValueError):
        _make_task(id="  ")
    with pytest.raises(ValueError):
        _make_task(persona_id="")


def test_task_roundtrip_dict():
    task = _make_task(data_deps=["t-002"], allowed_links=["t-003"], budget_tokens=1234)
    audit = TaskAudit(
        input_snapshot="snapshot",
        output_summary="summary",
        token_usage=456,
    )
    task.audit = audit
    restored = Task.from_dict(task.to_dict())
    assert restored.id == task.id
    assert restored.persona_id == task.persona_id
    assert restored.data_deps == ["t-002"]
    assert restored.allowed_links == ["t-003"]
    assert restored.budget_tokens == 1234
    assert restored.status == TaskStatus.PENDING
    assert restored.audit is not None
    assert restored.audit.token_usage == 456


def test_task_audit_clamps_negative_tokens():
    audit = TaskAudit(input_snapshot="s", output_summary="o", token_usage=-5)
    assert audit.token_usage == 0


def test_can_transition_matrix():
    # legal
    assert can_transition(TaskStatus.PENDING, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.PENDING, TaskStatus.BLOCKED)
    assert can_transition(TaskStatus.PENDING, TaskStatus.STOPPED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.DONE)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.FAILED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.BLOCKED)
    assert can_transition(TaskStatus.RUNNING, TaskStatus.STOPPED)
    assert can_transition(TaskStatus.FAILED, TaskStatus.RUNNING)
    assert can_transition(TaskStatus.BLOCKED, TaskStatus.RUNNING)
    # illegal
    assert not can_transition(TaskStatus.PENDING, TaskStatus.DONE)
    assert not can_transition(TaskStatus.DONE, TaskStatus.RUNNING)
    assert not can_transition(TaskStatus.STOPPED, TaskStatus.RUNNING)
    assert not can_transition(TaskStatus.DONE, TaskStatus.FAILED)
    assert not can_transition(TaskStatus.BLOCKED, TaskStatus.DONE)


def test_legal_targets():
    targets = legal_targets(TaskStatus.PENDING)
    assert TaskStatus.RUNNING in targets
    assert TaskStatus.DONE not in targets
    assert legal_targets(TaskStatus.DONE) == []


def test_state_machine_full_flow():
    task = _make_task()
    machine = TaskStateMachine(task)
    machine.start()
    assert task.status == TaskStatus.RUNNING
    audit = TaskAudit(input_snapshot="in", output_summary="out", token_usage=10)
    machine.complete(audit)
    assert task.status == TaskStatus.DONE
    assert task.audit is audit


def test_state_machine_illegal_transition_raises():
    task = _make_task()
    machine = TaskStateMachine(task)
    with pytest.raises(ValueError, match="illegal task transition"):
        machine.transition(TaskStatus.DONE)  # PENDING -> DONE not allowed


def test_state_machine_retry_after_failure():
    task = _make_task()
    machine = TaskStateMachine(task)
    machine.start()
    machine.fail()
    assert task.status == TaskStatus.FAILED
    machine.start()  # retry FAILED -> RUNNING
    assert task.status == TaskStatus.RUNNING


def test_state_machine_block_unblock_stop():
    task = _make_task()
    machine = TaskStateMachine(task)
    machine.block()  # PENDING -> BLOCKED
    assert task.status == TaskStatus.BLOCKED
    machine.unblock()  # BLOCKED -> RUNNING
    assert task.status == TaskStatus.RUNNING
    machine.stop()
    assert task.status == TaskStatus.STOPPED


def test_complete_requires_audit():
    """A task can never be marked DONE without an L2 audit record."""
    task = _make_task()
    machine = TaskStateMachine(task)
    machine.start()
    with pytest.raises(ValueError, match="audit"):
        machine.complete(None)
    assert task.status == TaskStatus.RUNNING


def test_collab_message():
    msg = CollabMessage(
        id="m-1",
        task_id="t-001",
        speaker="investing",
        reply_to="m-0",
        references=["audit-123"],
        content="回应你的观点",
        epistemic_tags=["需联网核实"],
    )
    d = msg.to_dict()
    assert d["reply_to"] == "m-0"
    assert d["references"] == ["audit-123"]
    assert d["epistemic_tags"] == ["需联网核实"]