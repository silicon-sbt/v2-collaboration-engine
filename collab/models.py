"""V2 collaboration engine: core data models.

Defines the task unit of work, its lifecycle status, the L2 audit record
attached to every completed task, and the horizontal-messaging message.
These types are shared by the state machine, the LangGraph executor (T3),
the manager arbitration (T5) and the async runner (T7), so changing a field
here affects all of them. See docs/AGENT_GUIDE.md section 2.1.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

DEFAULT_TASK_BUDGET_TOKENS = 80_000


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO timestamp back to a datetime (from_dict round-trip)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None



class TaskStatus(str, Enum):
    """Lifecycle status of a collaboration task.

    Transition rules live in collab.state_machine; this enum only names states.
    """

    PENDING = "pending"      # created, not started
    RUNNING = "running"      # executing
    DONE = "done"            # succeeded with auditable output (terminal)
    FAILED = "failed"        # execution failed (retryable -> RUNNING)
    BLOCKED = "blocked"      # blocked (dependency not ready / manager paused; unblock -> RUNNING)
    STOPPED = "stopped"      # cancelled by manager (terminal)

    @classmethod
    def terminal(cls) -> set["TaskStatus"]:
        return {cls.DONE, cls.STOPPED}

    @classmethod
    def active(cls) -> set["TaskStatus"]:
        return {cls.PENDING, cls.RUNNING, cls.BLOCKED}


class TaskAudit:
    """L2 audit record attached to a task (input snapshot / output summary / tokens).

    Design rule (roundtable resolution): this record is the single source of
    truth for arbitration (T5) AND horizontal referencing (T4) - audit what you
    arbitrate on, and reference what you audit.

    - input_snapshot: enough to replay/roll back the task.
    - output_summary: STRUCTURED text; must include referenced snapshot ids and
      key decision points so hard rules can validate it (machine-checkable).
    - output_reasoning: OPEN-DOMAIN reasoning text (the raw output); present so
      the audit is not just a filled-in template ("open + structured dual track",
      roundtable T3 review): hard rules check it exists, semantic consistency is
      left to manager arbitration (T5).
    - token_usage: objective counter auto-verified by the state machine; never
      self-reported by the agent.
    """

    __slots__ = (
        "input_snapshot",
        "output_summary",
        "output_reasoning",
        "token_usage",
        "prompt_tokens",
        "completion_tokens",
        "memory_tokens",
        "provider",
        "model",
        "cost_usd",
        "persona_id",
        "started_at",
        "finished_at",
    )

    def __init__(
        self,
        *,
        input_snapshot: str,
        output_summary: str,
        output_reasoning: str = "",
        token_usage: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        memory_tokens: int = 0,
        provider: str = "",
        model: str = "",
        cost_usd: float = 0.0,
        persona_id: str = "",
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        self.input_snapshot = input_snapshot
        self.output_summary = output_summary
        self.output_reasoning = output_reasoning
        self.token_usage = max(0, int(token_usage))
        self.prompt_tokens = max(0, int(prompt_tokens))
        self.completion_tokens = max(0, int(completion_tokens))
        self.memory_tokens = max(0, int(memory_tokens))
        self.provider = provider
        self.model = model
        self.cost_usd = max(0.0, float(cost_usd))
        self.persona_id = persona_id
        self.started_at = started_at or datetime.now(timezone.utc)
        self.finished_at = finished_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_snapshot": self.input_snapshot,
            "output_summary": self.output_summary,
            "output_reasoning": self.output_reasoning,
            "token_usage": self.token_usage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "memory_tokens": self.memory_tokens,
            "provider": self.provider,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "persona_id": self.persona_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class Task:
    """One unit of work in a mode-B collaboration.

    Fields:
      id: unique identifier (e.g. "t-001").
      persona_id: which persona executes this task.
      input: the instruction / input payload for the task.
      expected_output: description of the expected deliverable (arbitration basis).
      data_deps: task ids whose audited output may be referenced (data dependency).
      allowed_links: task ids this task may talk to horizontally (M1: hard-coded by manager).
      budget_tokens: per-task token quota (default 80k; global cap 400k lives in the runner).
      status: current lifecycle status.
      audit: L2 audit record, populated when the task finishes (DONE/FAILED).
    """

    __slots__ = (
        "id",
        "persona_id",
        "input",
        "expected_output",
        "data_deps",
        "allowed_links",
        "budget_tokens",
        "budget_soft_tokens",
        "status",
        "audit",
    )

    def __init__(
        self,
        *, 
        id: str,
        persona_id: str,
        input: str,
        expected_output: str = "",
        data_deps: list[str] | None = None,
        allowed_links: list[str] | None = None,
        budget_tokens: int = DEFAULT_TASK_BUDGET_TOKENS,
        budget_soft_tokens: int | None = None,
        status: TaskStatus = TaskStatus.PENDING,
        audit: TaskAudit | None = None,
    ) -> None:
        if not id.strip():
            raise ValueError("task id must not be empty")
        if not persona_id.strip():
            raise ValueError("persona_id must not be empty")
        self.id = id
        self.persona_id = persona_id
        self.input = input
        self.expected_output = expected_output
        self.data_deps = list(data_deps or [])
        self.allowed_links = list(allowed_links or [])
        self.budget_tokens = max(1, int(budget_tokens))
        # T12 soft budget: a warning threshold below the hard quota (default 80%).
        self.budget_soft_tokens = (
            max(0, int(budget_soft_tokens))
            if budget_soft_tokens is not None
            else max(0, int(self.budget_tokens * 0.8))
        )
        self.status = status
        self.audit = audit

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "persona_id": self.persona_id,
            "input": self.input,
            "expected_output": self.expected_output,
            "data_deps": list(self.data_deps),
            "allowed_links": list(self.allowed_links),
            "budget_tokens": self.budget_tokens,
            "budget_soft_tokens": self.budget_soft_tokens,
            "status": self.status.value,
            "audit": self.audit.to_dict() if self.audit else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Rebuild a Task from its dict form (used by persistence/status queries)."""
        audit_data = data.get("audit")
        return cls(
            id=str(data["id"]),
            persona_id=str(data["persona_id"]),
            input=str(data.get("input", "")),
            expected_output=str(data.get("expected_output", "")),
            data_deps=[str(x) for x in data.get("data_deps", [])],
            allowed_links=[str(x) for x in data.get("allowed_links", [])],
            budget_tokens=int(data.get("budget_tokens", DEFAULT_TASK_BUDGET_TOKENS)),
            budget_soft_tokens=data.get("budget_soft_tokens"),
            status=TaskStatus(data.get("status", TaskStatus.PENDING.value)),
            audit=(
                TaskAudit(
                    input_snapshot=str(audit_data.get("input_snapshot", "")),
                    output_summary=str(audit_data.get("output_summary", "")),
                    output_reasoning=str(audit_data.get("output_reasoning", "")),
                    token_usage=int(audit_data.get("token_usage", 0)),
                    prompt_tokens=int(audit_data.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(audit_data.get("completion_tokens", 0) or 0),
                    memory_tokens=int(audit_data.get("memory_tokens", 0) or 0),
                    provider=str(audit_data.get("provider", "")),
                    model=str(audit_data.get("model", "")),
                    cost_usd=float(audit_data.get("cost_usd", 0.0) or 0.0),
                    persona_id=str(audit_data.get("persona_id", "")),
                    started_at=_parse_dt(audit_data.get("started_at")),
                    finished_at=_parse_dt(audit_data.get("finished_at")),
                )
                if audit_data
                else None
            ),
        )


class CollabMessage:
    """A horizontal-collaboration message between tasks (T4).

    - reply_to: message id this message explicitly responds to (named reply).
    - references: audit snapshot ids of other tasks being cited (information reuse).
    - receivers: task ids this message is directed at (from sender's allowed_links).
    - Delivery follows the manager-approved link set, not broadcast.
    """

    __slots__ = ("id", "task_id", "speaker", "reply_to", "references", "receivers", "content", "epistemic_tags")

    def __init__(
        self,
        *, 
        id: str,
        task_id: str,
        speaker: str,
        reply_to: str | None = None,
        references: list[str] | None = None,
        receivers: list[str] | None = None,
        content: str = "",
        epistemic_tags: list[str] | None = None,
    ) -> None:
        self.id = id
        self.task_id = task_id
        self.speaker = speaker
        self.reply_to = reply_to
        self.references = list(references or [])
        self.receivers = list(receivers or [])
        self.content = content
        self.epistemic_tags = list(epistemic_tags or [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "speaker": self.speaker,
            "reply_to": self.reply_to,
            "references": list(self.references),
            "receivers": list(self.receivers),
            "content": self.content,
            "epistemic_tags": list(self.epistemic_tags),
        }


__all__ = [
    "Task",
    "TaskAudit",
    "TaskStatus",
    "CollabMessage",
    "DEFAULT_TASK_BUDGET_TOKENS",
]