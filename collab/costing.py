"""V2 collaboration engine: token-cost pricing and per-persona aggregation (T10).

The MCP/LLM layer already records OBJECTIVE usage on OpenAICompatLLM
(mcp_server/llm_client.py): last_usage = {prompt_tokens, completion_tokens,
total_tokens} plus model / provider_name. This module converts those counters into
a price. The data source is the LLM client - there is NO separate discovery layer.

Pricing uses a small conservative default table keyed by provider family, with an
optional model-specific override (provider:model). Unknown providers fall back to
a conservative estimate and are flagged (is_estimated) so a price is never
silently presented as precise (roundtable resolution). cost_summary separates
priced vs estimated so reports can label them (requirement 11.2-1).

See docs/v2-collaboration-engine-m2-requirements.md section 5.2.1 / 11.2-1 / 12.3.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# USD per 1K tokens as (input, output). Conservative on purpose: understating
# cost is worse than overstating for a budget/attribution system. "mock" is free.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek": (0.00014, 0.00028),
    "openai": (0.00015, 0.00060),
    "openrouter": (0.00015, 0.00060),
    "gemini": (0.00010, 0.00040),
    "mock": (0.0, 0.0),
}
DEFAULT_INPUT_RATE = 0.0002
DEFAULT_OUTPUT_RATE = 0.0006


def _rates(
    provider: str,
    model: str,
    rates: dict[str, tuple[float, float]],
) -> tuple[tuple[float, float], bool]:
    """Resolve (input, output) rates for provider+model.

    Prefers a model-specific override (provider:model), then provider-family,
    then a conservative default. Returns the rates and whether the price is an
    estimate (no explicit entry for this provider/model).
    """
    p = (provider or "").strip().lower()
    m = (model or "").strip()
    if m:
        key = p + ":" + m
        if key in rates:
            return rates[key], False
    if p in rates:
        return rates[p], False
    return (DEFAULT_INPUT_RATE, DEFAULT_OUTPUT_RATE), True


def price_tokens(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> float:
    """USD cost for one request.

    Unknown provider/model -> conservative default; check is_estimated() to label.
    """
    rates = pricing or DEFAULT_PRICES
    (in_rate, out_rate), _ = _rates(provider, model, rates)
    return max(
        0.0,
        (int(prompt_tokens) * in_rate + int(completion_tokens) * out_rate) / 1000.0,
    )


def is_estimated(
    provider: str,
    model: str = "",
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> bool:
    """True when the provider/model has no explicit price (cost is an estimate)."""
    rates = pricing or DEFAULT_PRICES
    _, estimated = _rates(provider, model, rates)
    return estimated


def cost_by_persona(
    results: list[dict[str, Any]],
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Aggregate audit cost_usd by the persona that produced each task result."""
    totals: dict[str, float] = {}
    for result in results:
        audit = result.get("audit")
        if not isinstance(audit, dict):
            continue
        persona = str(audit.get("persona_id") or result.get("persona_id") or "unknown")
        cost = float(audit.get("cost_usd") or 0.0)
        totals[persona] = round(totals.get(persona, 0.0) + cost, 6)
    return totals


def estimated_by_persona(
    results: list[dict[str, Any]],
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Per-persona cost that came from an ESTIMATED (unpriced) provider/model."""
    totals: dict[str, float] = {}
    for result in results:
        audit = result.get("audit")
        if not isinstance(audit, dict):
            continue
        if not is_estimated(str(audit.get("provider", "")), str(audit.get("model", "")), pricing=pricing):
            continue
        persona = str(audit.get("persona_id") or result.get("persona_id") or "unknown")
        cost = float(audit.get("cost_usd") or 0.0)
        totals[persona] = round(totals.get(persona, 0.0) + cost, 6)
    return totals


def cost_summary(
    results: list[dict[str, Any]],
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Total cost, priced/estimated split, and per-persona breakdown."""
    per_persona = cost_by_persona(results, pricing=pricing)
    est_persona = estimated_by_persona(results, pricing=pricing)
    total = round(sum(per_persona.values()), 6)
    estimated = round(sum(est_persona.values()), 6)
    return {
        "total_usd": total,
        "priced_usd": round(total - estimated, 6),
        "estimated_usd": estimated,
        "per_persona": per_persona,
        "estimated_persona": est_persona,
    }


def memory_summary(
    results: list[dict[str, Any]],
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Sub-accounting of the memory-injection portion of prompt cost (T20).

    memory_tokens are the prompt tokens spent injecting the retrieved memory
    context. They are ALREADY part of prompt_tokens/cost_usd, so this is a
    BREAKDOWN (subset), never an addition. Returns tokens + USD (priced at the
    input rate) + share of total cost.
    """
    tokens = 0
    usd = 0.0
    total = 0.0
    for result in results:
        audit = result.get("audit") if isinstance(result, dict) else None
        if not isinstance(audit, dict):
            continue
        mt = int(audit.get("memory_tokens", 0) or 0)
        tokens += mt
        provider = str(audit.get("provider", "") or "")
        model = str(audit.get("model", "") or "")
        if mt > 0:
            usd += price_tokens(provider, model, mt, 0, pricing=pricing)
        total += float(audit.get("cost_usd", 0.0) or 0.0)
    return {
        "memory_tokens": tokens,
        "memory_cost_usd": round(usd, 6),
        "memory_share": round(usd / total, 6) if total > 0 else 0.0,
    }


def waste_breakdown(
    results: list[dict[str, Any]],
    attempts: list[dict[str, Any]] | None = None,
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Split total LLM cost into *effective* (accepted output) vs *waste* (T11).

    effective = cost of final DONE + verdict.ok tasks.
    waste = total cost across ALL executions (attempts) minus effective, so
    failed / retried / over-budget attempts that never produced an accepted
    output are made visible and auditable (FR-ECO-4). Attempts are the
    per-execution records emitted by the executor (incl. transient/budget).
    """
    effective_tokens = 0
    effective_cost = 0.0
    for result in results:
        if result.get("status") != "done":
            continue
        verdict = result.get("verdict") or {}
        if verdict.get("ok", True) is False:
            continue
        audit = result.get("audit") or {}
        effective_tokens += int(audit.get("token_usage", 0) or 0)
        effective_cost += float(audit.get("cost_usd", 0) or 0)
    att = attempts or []
    total_tokens = sum(int(a.get("token_usage", 0) or 0) for a in att)
    total_cost = sum(float(a.get("cost_usd", 0) or 0) for a in att)
    waste_tokens = max(0, total_tokens - effective_tokens)
    waste_cost = round(max(0.0, total_cost - effective_cost), 6)
    # Precise waste attribution: a discarded attempt is one that (a) ended in
    # transient / budget / global-budget / generic failure, OR (b) was superseded
    # by a later retry (a manager_revise retry has failure_type=""), identified by
    # its attempt number being below that task's max attempt number.
    max_attempt: dict[str, int] = {}
    for a in att:
        tid = str(a.get("id"))
        max_attempt[tid] = max(max_attempt.get(tid, 0), int(a.get("attempt", 0) or 0))
    seen: set[tuple[str, str]] = set()
    reasons: list[dict[str, Any]] = []
    for a in att:
        tid = str(a.get("id"))
        ft = a.get("failure_type") or ""
        attempt_no = int(a.get("attempt", 0) or 0)
        discarded = ft in ("transient", "budget_exceeded", "global_budget") or (
            ft == "" and max_attempt.get(tid, 0) > 0 and attempt_no < max_attempt[tid]
        )
        if not discarded:
            continue
        key = (tid, ft or "superseded")
        if key in seen:
            continue
        seen.add(key)
        reasons.append(
            {
                "id": tid,
                "failure_type": ft or "superseded",
                "attempt": attempt_no,
                "token_usage": int(a.get("token_usage", 0) or 0),
                "cost_usd": float(a.get("cost_usd", 0.0) or 0.0),
            }
        )
    for result in results:
        if result.get("status") == "failed":
            rid = str(result.get("id"))
            ft = str(result.get("failure_type") or "failed")
            if (rid, ft) not in seen:
                seen.add((rid, ft))
                reasons.append({"id": rid, "failure_type": ft, "attempt": 0, "token_usage": 0, "cost_usd": 0.0})
    return {
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "effective_tokens": effective_tokens,
        "effective_cost_usd": round(effective_cost, 6),
        "waste_tokens": waste_tokens,
        "waste_cost_usd": waste_cost,
        "waste_reasons": reasons,
    }


def feedback_summary(
    attempts: list[dict[str, Any]] | None = None,
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Proxy for feedback/compliance quality (T11).

    compliance_effectiveness = tasks that had a retried/failed attempt and whose
    FINAL outcome is an accepted DONE. A computable proxy (roundtable: rename
    feedback to compliance, do not claim true quality). reason_specificity is
    intentionally NOT computed (cut per roundtable).

    Official recovery-rate formula: recovery_rate = tasks_that_retried_succeeded /
    tasks_that_retried (a retry-based metric, not 'final-passed / first-attempt').
    It is None when nothing was retried (no signal, not 'perfect') - callers must
    render 'N/A' rather than 0/1.
    """
    att = attempts or []
    results = results or []
    # A task "needed a retry" if it was executed more than once (captures
    # manager_revise + transient retries) OR had a failing/budget/lost attempt.
    counts = Counter(str(a.get("id")) for a in att)
    retried_ids = {tid for tid, c in counts.items() if c > 1} | {
        str(a["id"]) for a in att
        if (a.get("failure_type") or "") in ("transient", "budget_exceeded", "global_budget")
    }
    accepted = {
        r["id"] for r in results
        if r.get("status") == "done" and (r.get("verdict") or {}).get("ok", True) is not False
    }
    needed = len(retried_ids)
    succeeded = len(retried_ids & accepted)
    return {
        "tasks_that_retried": needed,
        "retries_that_succeeded": succeeded,
        # None when nothing was retried (there is no signal, not "perfect").
        "recovery_rate": round(succeeded / needed, 3) if needed else None,
    }


def rep_by_persona(
    results: list[dict[str, Any]],
    attempts: list[dict[str, Any]] | None = None,
    *,
    pricing: dict[str, tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Per-persona effective share of total cost (T12; exposed, NOT gated).

    A persona's reputation proxy = accepted (done+ok) cost / total cost for that
    persona. Exposed as a signal only - the roundtable deferred using it to gate
    budgets/priority (FR-ECO-5) until the bookkeeping is trusted.
    """
    effective: dict[str, float] = {}
    for result in results:
        if result.get("status") != "done":
            continue
        verdict = result.get("verdict") or {}
        if verdict.get("ok", True) is False:
            continue
        audit = result.get("audit") or {}
        # Align with cost_by_persona: fall back to the result top-level persona_id.
        persona = str(audit.get("persona_id") or result.get("persona_id") or "unknown")
        effective[persona] = effective.get(persona, 0.0) + float(audit.get("cost_usd", 0) or 0)
    total: dict[str, float] = {}
    for a in attempts or []:
        persona = str(a.get("persona_id") or "unknown")
        total[persona] = total.get(persona, 0.0) + float(a.get("cost_usd", 0) or 0)
    rep: dict[str, float] = {}
    for persona in set(list(effective) + list(total)):
        if total.get(persona, 0.0) > 0:
            rep[persona] = round(min(1.0, max(0.0, effective.get(persona, 0.0) / total[persona])), 3)
        # else: no attempt data for this persona -> omit. A missing denominator
        # must NOT read as a perfect reputation (roundtable).
    return rep


__all__ = [
    "DEFAULT_PRICES",
    "cost_by_persona",
    "cost_summary",
    "estimated_by_persona",
    "feedback_summary",
    "is_estimated",
    "price_tokens",
    "rep_by_persona",
    "waste_breakdown",
]
