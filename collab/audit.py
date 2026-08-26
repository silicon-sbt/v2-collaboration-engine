"""V2 collaboration engine: L2 audit construction and hard-rule validation (T2).

Design rule (roundtable resolution): the audit record is the single source of
truth for arbitration (T5) and horizontal referencing (T4). This module:

  - defines the STRUCTURED output-summary contract that hard rules can check,
  - validates a TaskAudit against those rules (deterministic, no LLM),
  - provides builders so executor (T3) produces conforming records.

token_usage is an objective counter taken from the LLM client (never the
agent's self-report); see mcp_server.llm_client.OpenAICompatLLM.last_usage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import TaskAudit

# Structured fields every output summary must carry so hard rules can check it.
# The labels are deliberately simple keywords; the executor fills them via
# render_summary_template so summaries are uniform and machine-checkable.
SUMMARY_REQUIRED_FIELDS: tuple[str, ...] = (
    "引用输入快照",
    "关键决策点",
    "任务结论",
)


@dataclass(frozen=True)
class AuditValidationResult:
    """Result of a hard-rule validation run."""

    ok: bool
    errors: list[str] = field(default_factory=list)


def render_summary_template(
    *,
    snapshot_ids: list[str] | None = None,
    decisions: list[str] | None = None,
    conclusion: str = "",
) -> str:
    """Build a structured output summary that satisfies the hard-rule contract.

    Example output:
        - 引用输入快照: snap-001、snap-002
        - 关键决策点: 1) 判断A; 2) 判断B
        - 任务结论: ...
    """
    snapshot_part = "、".join(snapshot_ids) if snapshot_ids else "N/A"
    if decisions:
        decision_part = "; ".join(f"{i + 1}) {d}" for i, d in enumerate(decisions))
    else:
        decision_part = "N/A"
    return (
        "- 引用输入快照: " + snapshot_part + "\n"
        "- 关键决策点: " + decision_part + "\n"
        "- 任务结论: " + (conclusion or "N/A")
    )


def validate_audit(
    audit: TaskAudit | None,
    *,
    require_summary_fields: bool = True,
) -> AuditValidationResult:
    """Deterministic hard-rule checks on an L2 audit record.

    Rules (all objective, no LLM involved):
      1. audit exists;
      2. input_snapshot is non-empty (needed for replay/rollback);
      3. output_summary is non-empty and (optionally) carries every structured
         field from SUMMARY_REQUIRED_FIELDS;
      4. token_usage is a non-negative integer.
    """
    errors: list[str] = []
    if audit is None:
        return AuditValidationResult(False, ["audit is missing"])

    if not audit.input_snapshot.strip():
        errors.append("input_snapshot is empty (required for replay/rollback)")

    if not audit.output_summary.strip():
        errors.append("output_summary is empty")
    elif require_summary_fields:
        for field_name in SUMMARY_REQUIRED_FIELDS:
            if field_name not in audit.output_summary:
                errors.append(
                    "output_summary missing required field: " + field_name,
                )

    if not audit.output_reasoning.strip():
        errors.append("output_reasoning is empty (open-domain track required)")

    if audit.token_usage < 0:
        errors.append("token_usage must be >= 0")
    if audit.prompt_tokens < 0 or audit.completion_tokens < 0:
        errors.append("prompt/completion_tokens must be >= 0")
    if audit.cost_usd < 0:
        errors.append("cost_usd must be >= 0")

    return AuditValidationResult(ok=not errors, errors=errors)


def build_audit(
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
) -> TaskAudit:
    """Construct a TaskAudit; raises ValueError when it fails hard-rule checks.

    Use this in the executor (T3) so every DONE task carries a valid audit.
    """
    # T23 adversarial hardening: a negative counter is a domain error and must be
    # rejected (not silently clamped) - validate_audit's <0 rules would otherwise
    # never fire because TaskAudit clamps to non-negative.
    if token_usage < 0 or prompt_tokens < 0 or completion_tokens < 0 or cost_usd < 0:
        raise ValueError("audit counters must be non-negative (token_usage/prompt_tokens/completion_tokens/cost_usd)")
    audit = TaskAudit(
        input_snapshot=input_snapshot,
        output_summary=output_summary,
        output_reasoning=output_reasoning,
        token_usage=token_usage,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        memory_tokens=memory_tokens,
        provider=provider,
        model=model,
        cost_usd=cost_usd,
        persona_id=persona_id,
        started_at=started_at,
        finished_at=finished_at or datetime.now(timezone.utc),
    )
    result = validate_audit(audit)
    if not result.ok:
        raise ValueError("audit failed hard-rule checks: " + "; ".join(result.errors))
    return audit


__all__ = [
    "AuditValidationResult",
    "SUMMARY_REQUIRED_FIELDS",
    "build_audit",
    "render_summary_template",
    "validate_audit",
]
