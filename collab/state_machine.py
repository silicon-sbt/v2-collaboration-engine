"""V2 collaboration engine: task state machine.

Defines the legal transitions between TaskStatus values. The machine is
deliberately small and pure (no I/O) so it can be unit-tested and reused by
the executor (T3) and the runner (T7). See docs/AGENT_GUIDE.md section 2.1.
"""

from __future__ import annotations

from .models import Task, TaskStatus

# Legal transitions: {from_status: {to_status}}.
# - Terminal states (DONE, STOPPED) have no outgoing edges: a finished task
#   is never silently resurrected. Retry after FAILED/BLOCKED goes through
#   RUNNING again (with a fresh attempt).
_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.STOPPED},
    TaskStatus.RUNNING: {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.STOPPED},
    TaskStatus.FAILED: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.STOPPED},
    TaskStatus.BLOCKED: {TaskStatus.RUNNING, TaskStatus.STOPPED},
    TaskStatus.DONE: set(),
    TaskStatus.STOPPED: set(),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return whether moving from ``current`` to ``target`` is legal."""
    return target in _TRANSITIONS.get(current, set())


def legal_targets(current: TaskStatus) -> list[TaskStatus]:
    """List statuses reachable from ``current`` (for UI/schema hints)."""
    return sorted(_TRANSITIONS.get(current, set()), key=lambda s: s.value)


class TaskStateMachine:
    """State-machine helper bound to a concrete Task.

    Example:
        machine = TaskStateMachine(task)
        machine.transition(TaskStatus.RUNNING)   # mutates task.status
        machine.transition(TaskStatus.DONE, audit=audit)
    """

    def __init__(self, task: Task) -> None:
        self.task = task

    def transition(self, target: TaskStatus) -> TaskStatus:
        """Apply a transition in place; raise ValueError on illegal moves."""
        current = self.task.status
        if not can_transition(current, target):
            raise ValueError(
                "illegal task transition: " + current.value + " -> " + target.value
            )
        self.task.status = target
        return target

    def start(self) -> TaskStatus:
        """Move PENDING -> RUNNING (or resume FAILED/BLOCKED -> RUNNING)."""
        return self.transition(TaskStatus.RUNNING)

    def complete(self, audit) -> TaskStatus:
        """Finish RUNNING -> DONE and attach the L2 audit record.

        The audit is attached before the state change so a task can never be
        marked DONE without an auditable record (single-source-of-truth rule).
        """
        if audit is None:
            raise ValueError("complete() requires an audit record")
        self.task.audit = audit
        return self.transition(TaskStatus.DONE)

    def fail(self) -> TaskStatus:
        return self.transition(TaskStatus.FAILED)

    def block(self) -> TaskStatus:
        return self.transition(TaskStatus.BLOCKED)

    def unblock(self) -> TaskStatus:
        return self.transition(TaskStatus.RUNNING)

    def stop(self) -> TaskStatus:
        return self.transition(TaskStatus.STOPPED)


__all__ = ["TaskStateMachine", "can_transition", "legal_targets"]
