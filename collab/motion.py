"""V2 collaboration engine: FR11 meeting-motion data layer (minimal, T13).

FR11 lets a sub-agent (task) apply to convene a mode-A roundtable. The FULL
mechanism - manager LLM review, reusing V1 roundtable for a double output,
participant add/remove, per-task free-discretion quota, MERGED semantics - is M3.
This M2 slice is the *pure data layer*:

  - CollabMotion (a request: topic / rationale / proposed participants / budget source),
  - a decision helper enforcing "reject must carry a reason" (auditable),
  - a same-topic merge helper,
  - and a small in-memory MotionStore to record/query/decide motions with a
    conclusion anchored to an audit snapshot / CollabMessage (single source of
    truth: do NOT create a second fact orphanage).

See docs/v2-collaboration-engine-m2-requirements.md section 5.3 / 9.5 / 11.2-4.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import json
import sqlite3
from typing import Any

_BUDGET_SOURCES = ("task", "global")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _new_motion_id() -> str:
    return "motion-" + uuid.uuid4().hex[:12]


class MotionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    EXPIRED = "expired"


@dataclass
class CollabMotion:
    """A sub-agent request to convene a roundtable (minimal data layer).

    Fields:
      id: motion id (motion-<hex>).
      task_id: the requesting sub-agent's task.
      topic: what the meeting is about.
      rationale: why a meeting is needed (quality gates a retry).
      proposed_participants: requested participants (manager may change).
      budget_source: "task" | "global" (declared at request time).
      status: MotionStatus.
      decided_by: who decided (manager persona).
      decision_reason: mandatory for rejection.
      committee: the manager's final participant set (adjusted).
      outputs: double output (applicant + manager) + cc list.
      audit_anchor: audit snapshot/collab-message id anchoring the conclusion.
      created_at / decided_at: ISO timestamps.
    """

    task_id: str
    topic: str
    rationale: str
    id: str = ""
    proposed_participants: list[str] = field(default_factory=list)
    budget_source: str = "task"
    status: MotionStatus = MotionStatus.PENDING
    decided_by: str = ""
    decision_reason: str = ""
    committee: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    audit_anchor: str = ""
    created_at: datetime = field(default_factory=_now)
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = _new_motion_id()
        if not self.task_id.strip():
            raise ValueError("motion requires a non-empty task_id")
        if not self.topic.strip():
            raise ValueError("motion requires a non-empty topic")
        if not self.rationale.strip():
            raise ValueError("motion requires a non-empty rationale")
        if self.budget_source not in _BUDGET_SOURCES:
            raise ValueError("budget_source must be one of " + str(_BUDGET_SOURCES))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "topic": self.topic,
            "rationale": self.rationale,
            "proposed_participants": list(self.proposed_participants),
            "budget_source": self.budget_source,
            "status": self.status.value,
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
            "committee": list(self.committee),
            "outputs": dict(self.outputs),
            "audit_anchor": self.audit_anchor,
            "created_at": _iso(self.created_at),
            "decided_at": _iso(self.decided_at) if self.decided_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CollabMotion":
        return cls(
            id=str(data.get("id") or _new_motion_id()),
            task_id=str(data.get("task_id", "")),
            topic=str(data.get("topic", "")),
            rationale=str(data.get("rationale", "")),
            proposed_participants=[str(x) for x in data.get("proposed_participants", [])],
            budget_source=str(data.get("budget_source", "task")),
            status=MotionStatus(data.get("status", MotionStatus.PENDING.value)),
            decided_by=str(data.get("decided_by", "")),
            decision_reason=str(data.get("decision_reason", "")),
            committee=[str(x) for x in data.get("committee", [])],
            outputs=dict(data.get("outputs", {}) or {}),
            audit_anchor=str(data.get("audit_anchor", "")),
            created_at=_parse_dt(data.get("created_at")) or _now(),
            decided_at=_parse_dt(data.get("decided_at")),
        )


def apply_decision(
    motion: CollabMotion,
    *,
    decision: str,
    decided_by: str = "",
    reason: str = "",
    committee: list[str] | None = None,
    audit_anchor: str = "",
) -> CollabMotion:
    """Apply an APPROVED / REJECTED decision to a motion (in place, returns it).

    Auditability: a DECIDER (decided_by) is required for any decision; a REJECTION
    MUST carry a reason; otherwise ValueError keeps the motion PENDING for a
    better-rationale retry. An APPROVAL takes the (possibly adjusted) committee
    (defaults to the applicant proposal when none supplied) and stamps the decision.
    """
    if motion.status != MotionStatus.PENDING:
        raise ValueError("motion is not pending: " + motion.status.value)
    decision = (decision or "").strip().lower()
    if decision in ("approve",):
        decision = "approved"
    elif decision in ("reject",):
        decision = "rejected"
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be approved or rejected")
    if not decided_by.strip():
        raise ValueError("decision requires a decided_by (auditability)")
    if decision == "rejected" and not reason.strip():
        raise ValueError("rejection must carry a reason (auditability)")
    if decision == "approved":
        motion.committee = [str(x) for x in (committee if committee is not None else motion.proposed_participants)]
    motion.decided_by = decided_by
    motion.decision_reason = reason
    if audit_anchor:
        motion.audit_anchor = audit_anchor
    motion.status = MotionStatus.APPROVED if decision == "approved" else MotionStatus.REJECTED
    motion.decided_at = _now()
    return motion


def merge_same_topic(motions: list[CollabMotion], *, topic_key: str = "topic") -> list[CollabMotion]:
    """Merge PENDING motions that share a topic into one (others -> MERGED).

    Records which motions were absorbed (survivor.outputs['merged_from']) and
    stamps the merged ones with decider + reason for auditability.
    """
    first_by_topic: dict[str, CollabMotion] = {}
    for motion in motions:
        if motion.status != MotionStatus.PENDING:
            continue
        key = (topic_key and getattr(motion, topic_key, "") or motion.topic).strip()
        if key in first_by_topic:
            survivor = first_by_topic[key]
            survivor.proposed_participants = list(
                dict.fromkeys(survivor.proposed_participants + motion.proposed_participants)
            )
            merged_from = list(survivor.outputs.get("merged_from", []))
            if motion.id not in merged_from:
                merged_from.append(motion.id)
            survivor.outputs["merged_from"] = merged_from
            motion.status = MotionStatus.MERGED
            motion.decided_by = "manager"
            motion.decision_reason = "merged into " + survivor.id
            motion.decided_at = _now()
        else:
            first_by_topic[key] = motion
    return motions


class MotionStore:
    """Motion registry (in-memory working set; optional SQLite persistence).

    With a db_path the store hydrates from disk on init and persists every
    mutation, so motions survive across CLI invocations (T18). Without a
    db_path it is in-memory - the M2 behaviour, safe for in-process graph
    branches.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else None
        self._motions: dict[str, CollabMotion] = {}
        self._lock = threading.Lock()
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
            self._load_all()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS motions (id TEXT PRIMARY KEY, data TEXT NOT NULL)")

    def _load_all(self) -> None:
        with self._conn() as conn:
            rows = conn.execute("SELECT data FROM motions").fetchall()
        for row in rows:
            try:
                m = CollabMotion.from_dict(json.loads(str(row["data"])))
                self._motions[m.id] = m
            except Exception:
                continue

    def _save(self, motion: CollabMotion) -> None:
        if self.db_path is None:
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO motions (id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (motion.id, json.dumps(motion.to_dict(), ensure_ascii=False)),
            )

    def add(self, motion: CollabMotion) -> CollabMotion:
        with self._lock:
            self._motions[motion.id] = motion
            self._save(motion)
        return motion

    def get(self, motion_id: str) -> CollabMotion | None:
        with self._lock:
            return self._motions.get(motion_id)

    def list(self, status: MotionStatus | None = None) -> list[CollabMotion]:
        with self._lock:
            motions = list(self._motions.values())
        if status is not None:
            motions = [m for m in motions if m.status == status]
        return sorted(motions, key=lambda m: _iso(m.created_at))

    def decide(self, motion_id: str, **kwargs: Any) -> CollabMotion:
        with self._lock:
            motion = self._motions.get(motion_id)
            if motion is None:
                raise ValueError("unknown motion id: " + motion_id)
            res = apply_decision(motion, **kwargs)
            self._save(motion)
            return res

    def merge_pending(self) -> list[CollabMotion]:
        with self._lock:
            motions = list(self._motions.values())
            merge_same_topic(motions)
            for m in motions:
                if m.status == MotionStatus.MERGED:
                    self._save(m)
            return motions


__all__ = [
    "CollabMotion",
    "MotionStatus",
    "MotionStore",
    "apply_decision",
    "merge_same_topic",
];
