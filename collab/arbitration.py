"""V2 collaboration engine: layered arbitration (T5).

T5 implements the roundtable-resolved arbitration chain for DONE tasks:

  1. HARD RULES (deterministic, no LLM):
     - L2 audit validity (delegated to collab.audit.validate_audit)
     - decision-verb/object conflict detection (block explicit self-
       contradiction; high-entropy verbs only)
     - anchor-coverage confidence (T4 review: mechanically verifiable,
       anchored to independently-checkable dependency snapshots)
  2. MANAGER PROVISIONAL (LLM): judge whether the output satisfies the task
     expected_output; verdict PASS or REVISE + reason. Provisional, not final:
     the report carries the verdict for auditability (appeal via FR11 in M2).

A task failing hard rules or manager review is marked FAILED with the reason
attached, so the collaboration report shows exactly why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .audit import validate_audit
from .models import Task, TaskAudit

# High-entropy decision verbs only (T3 review: exclude low-entropy verbs).
POSITIVE_VERBS = ("采用", "采纳", "推荐", "确认", "支持", "同意")
NEGATIVE_VERBS = ("放弃", "否决", "拒绝", "反对", "排除", "不采用")
_ALL_VERBS = POSITIVE_VERBS + NEGATIVE_VERBS

_OBJECT_RE = re.compile(r"[\u4e00-\u9fff\w]+")


@dataclass(frozen=True)
class Conflict:
    """An explicit self-contradiction between two decision statements."""

    obj: str
    positive: str
    negative: str

    def to_dict(self) -> dict[str, Any]:
        return {"obj": self.obj, "positive": self.positive, "negative": self.negative}


@dataclass(frozen=True)
class AnchorCoverage:
    """How much of the decision content is backed by cross-task anchors."""

    decision_count: int
    anchor_count: int
    coverage: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_count": self.decision_count,
            "anchor_count": self.anchor_count,
            "coverage": round(self.coverage, 3),
        }


def detect_decision_conflicts(*texts: str) -> list[Conflict]:
    """Detect explicit verb/object contradictions across the given texts.

    For every high-entropy verb followed by a noun phrase, if the SAME object
    appears under both a positive and a negative verb the pair is reported.
    """
    object_sentiment: dict[str, dict[str, str]] = {}
    for text in texts:
        if not text:
            continue
        pattern = "(" + "|".join(_ALL_VERBS) + ")([^\n。；;]{1,40})"
        for match in re.finditer(pattern, text):
            verb = match.group(1)
            tail = match.group(2).strip()
            obj_match = _OBJECT_RE.search(tail)
            if not obj_match:
                continue
            obj = obj_match.group(0)[:20]
            entry = object_sentiment.setdefault(obj, {"pos": "", "neg": ""})
            if verb in POSITIVE_VERBS:
                entry["pos"] = entry["pos"] or verb
            elif verb in NEGATIVE_VERBS:
                entry["neg"] = entry["neg"] or verb
    conflicts: list[Conflict] = []
    for obj, sentiment in object_sentiment.items():
        if sentiment["pos"] and sentiment["neg"]:
            conflicts.append(Conflict(obj=obj, positive=sentiment["pos"], negative=sentiment["neg"]))
    return conflicts


def compute_anchor_coverage(output_summary: str, snapshot_ids: list[str]) -> AnchorCoverage:
    """Mechanical confidence: decision points in the summary vs cross-task anchors.

    Decisions are counted from the structured summary lines; anchors are the
    dependency snapshot ids cited. coverage = anchors / decisions clamped to
    [0,1] (1.0 when there are no decisions). Low coverage = mostly inference.
    """
    decision_count = 0
    for line in (output_summary or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("- 关键决策点") or stripped.startswith("关键决策点:"):
            found = re.findall(r"[0-9]+\s*\)", stripped)
            if found:
                decision_count = max(decision_count, len(found))
            elif "N/A" not in stripped:
                decision_count = max(decision_count, 1)
    anchors = [s for s in snapshot_ids if s]
    if decision_count <= 0:
        return AnchorCoverage(decision_count=0, anchor_count=len(anchors), coverage=1.0)
    return AnchorCoverage(
        decision_count=decision_count,
        anchor_count=len(anchors),
        coverage=min(len(anchors) / decision_count, 1.0),
    )


@dataclass(frozen=True)
class Verdict:
    """Combined hard-rule + manager outcome for one task."""

    task_id: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    coverage: AnchorCoverage | None = None
    manager: str = ""
    manager_reason: str = ""
    failure_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "ok": self.ok,
            "reasons": list(self.reasons),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "coverage": self.coverage.to_dict() if self.coverage else None,
            "manager": self.manager,
            "manager_reason": self.manager_reason,
            "failure_type": self.failure_type,
        }


def hard_rules_check(
    task: Task,
    audit: TaskAudit | None,
    snapshot_ids: list[str] | None = None,
) -> Verdict:
    """Deterministic checks: audit validity, verb conflicts, anchor coverage.

    Verdict is frozen, so build all fields up front (no in-place mutation).
    """
    reasons: list[str] = []
    conflicts: list[Conflict] = []
    coverage: AnchorCoverage | None = None
    failure_type = ""
    audit_result = validate_audit(audit)
    if not audit_result.ok:
        reasons.extend(audit_result.errors)
        failure_type = "audit_invalid"
    if audit is not None:
        conflicts = detect_decision_conflicts(audit.output_summary, audit.output_reasoning)
        coverage = compute_anchor_coverage(audit.output_summary, snapshot_ids or [])
        if conflicts:
            reasons.append("显性决策矛盾: " + "; ".join(c.obj for c in conflicts))
            failure_type = failure_type or "conflict"
    return Verdict(
        task_id=task.id,
        ok=not reasons,
        reasons=reasons,
        conflicts=conflicts,
        coverage=coverage,
        failure_type=failure_type,
    )


def manager_arbitrate(
    llm: Any,
    task: Task,
    audit: TaskAudit | None,
    *,
    root_dir: Any = None,
) -> tuple[str, str]:
    """Provisional LLM judgement: does the output satisfy expected_output?

    Returns (verdict, reason); "pass"/"revise". Falls back to pass when no
    expected_output is declared. Verdict is provisional - appeal via FR11 (M2).
    """
    if not task.expected_output.strip() or audit is None:
        return "pass", "no expected_output declared"
    prompt = [
        "[COLLAB_MANAGER_ARBITRATION]",
        "任务：" + task.input,
        "期望产出：" + task.expected_output,
        "产出摘要：" + (audit.output_summary or ""),
        "产出原文（开放域）：" + (audit.output_reasoning or "")[:2000],
        "请裁决该产出是否满足任务意图。只输出两行：第一行 PASS 或 REVISE；第二行一句原因。",
    ]
    try:
        text = (llm.generate("\n\n".join(prompt)) or "").strip()
    except Exception as exc:
        return "revise", "manager arbitration failed: " + str(exc)
    # Parse the FIRST line exactly: "REVISE" / "PASS" as the leading token.
    # Full-text contains-matching misjudges when the reason mentions the other
    # keyword (e.g. "must PASS quality checks" inside a REVISE verdict).
    first_line = (text.splitlines()[0] if text.splitlines() else text).strip().upper()
    if first_line.startswith("REVISE"):
        return "revise", text[:200]
    return "pass", text[:200]


__all__ = [
    "AnchorCoverage",
    "Conflict",
    "Verdict",
    "compute_anchor_coverage",
    "detect_decision_conflicts",
    "hard_rules_check",
    "manager_arbitrate",
]
