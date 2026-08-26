"""V2 collaboration engine: LangGraph executor with manager dispatch (T3).

Mode B execution graph (map-reduce):

    START -> manager (Send fan-out) -> execute_task x N -> collect -> END

- manager: dispatches every PENDING task via `Send` (parallel branches).
- execute_task: runs one task with a persona-scoped prompt, citing audited
  outputs of its data_deps (information reuse), and writes an L2 audit.
- collect: runs after each branch; once every task reached a terminal state
  it emits the collaboration report.

State uses reducers so parallel branches accumulate without clobbering:
`results`/`messages`/`errors` append, `token_total` sums. The original task
definitions stay in `tasks`; execution outcomes live in `results` keyed by id.
See docs/AGENT_GUIDE.md section 3.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from operator import add
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .llm import resolve_llm
from .persona import persona_hint
from .tokenize import tokenize

from .arbitration import hard_rules_check, manager_arbitrate
from .audit import build_audit, render_summary_template
from .costing import cost_summary, feedback_summary, memory_summary, price_tokens, rep_by_persona, waste_breakdown
from .models import CollabMessage, Task, TaskAudit, TaskStatus
from .state_machine import TaskStateMachine
from .memory import build_memory_context, memory_entries_from_output


def _merge_results(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reducer: merge results by task id (arbitration may revise an outcome)."""
    by_id = {str(r.get("id")): r for r in current}
    for result in incoming:
        by_id[str(result.get("id"))] = result
    return list(by_id.values())

class CollabState(TypedDict, total=False):
    """Graph state for one collaboration run.

    tasks: original task definitions (set once, never reduced).
    results: per-task execution outcomes, appended by parallel branches.
    messages: horizontal messages (T4; reserved now).
    token_total: summed LLM token usage (T6 budget basis).
    errors: collected failures (deterministic retry information).
    final_report: produced by collect when all tasks are terminal.
    """

    tasks: list[dict[str, Any]]
    results: Annotated[list[dict[str, Any]], _merge_results]
    messages: Annotated[list[dict[str, Any]], add]
    token_total: Annotated[int, add]
    errors: Annotated[list[str], add]
    attempts: Annotated[list[dict[str, Any]], add]  # T11: per-execution cost/outcome for waste & feedback metrics
    mode: str                     # T14: "wave" | "parallel" (runtime mode)
    experimental: bool            # T14: parallel is experimental
    parallel_note: str            # T14: why parallel fell back to wave
    final_report: str


def resolve_mode(tasks: list[dict[str, Any]], mode: str = "wave") -> tuple[str, bool, str]:
    """Determine the effective execution mode (T14).

    'parallel' is only allowed when EVERY task has empty data_deps (no data
    dependency to wait on); otherwise it falls back to 'wave' (the current wave
    scheduler already parallelises independent tasks). Parallel is a MARKER over
    that existing scheduling - it does not swap in a second scheduler / lock
    (roundtable). It is marked experimental until proven. Empty tasks fall back
    to wave (nothing to parallelise, not a vacuous 'experimental').
    """
    mode = (mode or "wave").strip().lower()
    if mode not in ("wave", "parallel"):
        raise ValueError("mode must be wave or parallel")
    if mode == "parallel":
        if not tasks or any(t.get("data_deps") for t in tasks):
            return "wave", False, "parallel requires no data_deps; fell back to wave"
        return "parallel", True, ""
    return "wave", False, ""


TERMINAL_STATUSES = {TaskStatus.DONE.value, TaskStatus.FAILED.value, TaskStatus.STOPPED.value}
# Statuses that end a run for collect: BLOCKED counts because the blocker node
# writes it only when no wave can ever execute the task (M1: no unblock path).
RUN_TERMINAL_STATUSES = TERMINAL_STATUSES | {TaskStatus.BLOCKED.value}
# T6 failure recovery + budget:
MAX_TASK_RETRIES = 1  # retry once for recoverable failures (manager_revise / transient)
GLOBAL_TOKEN_BUDGET = 400_000  # global cap; per-task budget lives on Task.budget_tokens
GLOBAL_BUDGET_SOFT = int(GLOBAL_TOKEN_BUDGET * 0.8)  # T12 soft threshold (warning level, stop only at hard cap)


def _build_task_prompt(
    task: Task,
    *,
    references: list[str],
    incoming_messages: list[str] | None = None,
    retry_feedback: str = "",
    persona_hint: str = "",
    memory_context: str = "",
) -> str:
    """Assemble the execution prompt: persona hint + task input + cited outputs
    + horizontal messages (T4): peer summaries this task may respond to.
    """
    parts = ["[COLLAB_TASK_EXECUTION]"]
    if persona_hint:
        parts.append("你以如下角色执行任务：\n" + persona_hint)
    if memory_context.strip():
        parts.append(memory_context)
    parts.append("任务：" + task.input)
    if task.expected_output:
        parts.append("期望产出：" + task.expected_output)
    if references:
        parts.append("可引用的其他任务产出（引用时在句末标注来源，不要逐字照搬）：\n" + "\n\n".join(references))
    else:
        parts.append("暂无可引用的其他任务产出。")
    if retry_feedback.strip():
        parts.append("上一次尝试的反馈（请据此改进后再产出）：" + retry_feedback.strip())
    incoming = incoming_messages or []
    if incoming:
        parts.append("协作伙伴的消息（你可以回应、反驳或采纳其中的观点；回应时明确指向对方）：\n" + "\n\n".join(incoming))
    parts.append("请直接输出你的成果，不要加额外标题。")
    return "\n\n".join(parts)


def _persona_hint(persona_id: str, root_dir: Any) -> str:
    """Best-effort persona summary; falls back to the persona id."""
    return persona_hint(persona_id, root_dir)


def _token_usage(llm: Any) -> int:
    """Objective token counter from the LLM client; 0 when unavailable (mock)."""
    usage = getattr(llm, "last_usage", None)
    if isinstance(usage, dict):
        return int(usage.get("total_tokens", 0) or 0)
    return 0


def _executor_node_factory(
    llm: Any,
    *,
    root_dir: Any = None,
    memory_store: Any = None,
) -> Callable[[CollabState], dict[str, Any]]:
    """Build the execute_task node, capturing the LLM and repo root."""

    def execute_task_node(state: CollabState) -> dict[str, Any]:
        task_dict = dict(state.get("task") or {})
        task = Task.from_dict(task_dict)
        machine = TaskStateMachine(task)
        machine.start()

        # Manager aggregates dependency outputs + incoming messages into the
        # Send payload context (Send branches do not share state in LangGraph).
        context = state.get("context") or {}
        dep_map: dict[str, str] = dict(context.get("references") or {})
        references = list(dep_map.values())
        snapshot_ids = list(dep_map.keys())
        incoming = list(context.get("incoming") or [])

        # T6: retry context (manager feedback / previous failure) comes in the
        # same Send payload context as references/incoming.
        previous = context
        retry_feedback = previous.get("retry_feedback", "")
        attempts = int(previous.get("attempts", 1))

        memory_context = ""
        if memory_store is not None:
            memory_context = build_memory_context(memory_store.search(task.persona_id, task.input))
        memory_tokens = len(tokenize(memory_context)) if memory_context else 0
        prompt = _build_task_prompt(
            task,
            references=references,
            incoming_messages=incoming,
            retry_feedback=retry_feedback,
            persona_hint=_persona_hint(task.persona_id, root_dir),
            memory_context=memory_context,
        )
        started = datetime.now(timezone.utc)
        try:
            content = llm.generate(prompt)
            token_used = _token_usage(llm)
            # T10 cost: capture the objective usage split + identity from the LLM
            # client (already on it), then price it. Never trust a self-report.
            usage = getattr(llm, "last_usage", None)
            if not isinstance(usage, dict):
                usage = {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            provider = str(getattr(llm, "provider_name", "") or "")
            model = str(getattr(llm, "model", "") or "")
            cost_usd = price_tokens(provider, model, prompt_tokens, completion_tokens)
            # T6/T12: task budget roll-up across retries + soft/hard thresholds.
            task_token_total = int(previous.get("task_token_total", 0)) + token_used
            soft_warn = task_token_total > task.budget_soft_tokens
            base_attempt = {
                "id": task.id,
                "persona_id": task.persona_id,
                "attempt": attempts,
                "token_usage": token_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "memory_tokens": memory_tokens,
                "cost_usd": cost_usd,
                "provider": provider,
                "model": model,
                "soft_budget_warning": soft_warn,
            }
            # Hard per-task budget (T6): exceeding the quota fails the task (never retried).
            if task_token_total > task.budget_tokens:
                machine.fail()
                return {
                    "results": [
                        {
                            "id": task.id,
                            "status": TaskStatus.FAILED.value,
                            "attempts": attempts,
                            "failure_type": "budget_exceeded",
                            "overspend_kind": "loss",
                            "error": "task token budget exceeded: " + str(task_token_total) + " > " + str(task.budget_tokens),
                        }
                    ],
                    "token_total": token_used,
                    "attempts": [dict(base_attempt, status="failed", failure_type="budget_exceeded")],
                }
            audit = build_audit(
                input_snapshot=prompt[:2000],
                output_summary=render_summary_template(
                    snapshot_ids=snapshot_ids or None,
                    decisions=[task.expected_output] if task.expected_output else None,
                    conclusion=content[:200],
                ),
                output_reasoning=content,  # open-domain track (raw output)
                token_usage=token_used,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                memory_tokens=memory_tokens,
                provider=provider,
                model=model,
                cost_usd=cost_usd,
                persona_id=task.persona_id,
                started_at=started,
            )
            machine.complete(audit)
            # T4: deliver a horizontal message (summary + snapshot id) to peers
            # in allowed_links - the directed weak-mesh channel. The manager
            # (wave routing) decides who may talk to whom via allowed_links.
            peer_message = CollabMessage(
                id=task.id + "-msg",
                task_id=task.id,
                speaker=task.persona_id,
                references=snapshot_ids,
                receivers=task.allowed_links,
                content=render_summary_template(
                    snapshot_ids=snapshot_ids or None,
                    decisions=[task.expected_output] if task.expected_output else None,
                    conclusion=content[:120],
                ),
                epistemic_tags=["横向交流"],
            )
            return {
                "results": [
                    {
                        "id": task.id,
                        "status": TaskStatus.DONE.value,
                        "output": content,
                        "attempts": attempts,
                        "task_token_total": task_token_total,
                        "soft_budget_warning": soft_warn,
                        "overspend_kind": "debt" if soft_warn else "",
                        "audit": audit.to_dict(),
                    }
                ],
                "messages": [peer_message.to_dict()],
                "token_total": token_used,
                "attempts": [dict(base_attempt, status="done", failure_type="")],
            }
        except Exception as exc:
            machine.fail()
            return {
                "results": [
                    {
                        "id": task.id,
                        "status": TaskStatus.FAILED.value,
                        "attempts": attempts,
                        "failure_type": "transient",
                        "task_token_total": int(previous.get("task_token_total", 0)) + _token_usage(llm),
                        "error": str(exc),
                    }
                ],
                "errors": ["task " + task.id + " failed: " + str(exc)],
                "token_total": _token_usage(llm),
                "attempts": [
                    {
                        "id": task.id,
                        "attempt": attempts,
                        "status": "failed",
                        "failure_type": "transient",
                        "token_usage": _token_usage(llm),
                        "prompt_tokens": int((getattr(llm, "last_usage", None) or {}).get("prompt_tokens", 0) or 0),
                        "completion_tokens": int((getattr(llm, "last_usage", None) or {}).get("completion_tokens", 0) or 0),
                        "memory_tokens": memory_tokens,
                        "cost_usd": price_tokens(
                            str(getattr(llm, "provider_name", "") or ""),
                            str(getattr(llm, "model", "") or ""),
                            int((getattr(llm, "last_usage", None) or {}).get("prompt_tokens", 0) or 0),
                            int((getattr(llm, "last_usage", None) or {}).get("completion_tokens", 0) or 0),
                        ),
                        "provider": str(getattr(llm, "provider_name", "") or ""),
                        "model": str(getattr(llm, "model", "") or ""),
                    }
                ],
            }

    return execute_task_node


def _manager_node(state: CollabState) -> dict[str, Any]:
    """Manager stub: the conditional edge performs the Send fan-out."""
    return {}


def _terminal_ids(state: CollabState) -> set[str]:
    """Ids whose results reached a terminal status."""
    return {
        result.get("id")
        for result in state.get("results", [])
        if result.get("status") in TERMINAL_STATUSES
    }


def _verify_blocked_reachability(
    tasks: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[str]:
    """Static reachability re-check for BLOCKED tasks (roundtable T3 review #2).

    For every task reported BLOCKED, walk its data_deps closure. A BLOCKED
    status is only legitimate when the closure contains NO terminal (DONE)
    outcome - i.e. the dependency chain could never satisfy. If a DONE task is
    reachable, the blocker mislabelled it and we surface a discrepancy instead
    of trusting the detector blindly (indirect cycles A->B->C->A must also be
    caught: their closure is all-BLOCKED/PENDING with no DONE node).
    """
    terminal_done = {
        result.get("id")
        for result in results
        if result.get("status") == TaskStatus.DONE.value
    }
    result_status = {result.get("id"): result.get("status") for result in results}
    # Map task id -> its declared data_deps (single source of truth; do NOT parse
    # dependency ids out of error strings, that is brittle).
    deps_by_task = {
        str(task_dict.get("id")): [str(dep) for dep in task_dict.get("data_deps", [])]
        for task_dict in tasks
    }
    discrepancies: list[str] = []
    for result in results:
        if result.get("status") != TaskStatus.BLOCKED.value:
            continue
        task_id = str(result.get("id"))
        visited: set[str] = set()
        stack = list(deps_by_task.get(task_id, []))
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            if node in terminal_done:
                discrepancies.append(
                    "task " + task_id + " blocked but reachable DONE dep: " + node,
                )
                break
            if node not in result_status:
                # Unknown dependency id: cannot verify it ever runs - surface it
                # as a discrepancy instead of silently treating it as blocked.
                discrepancies.append(
                    "task " + task_id + " blocked by unknown dep id: " + node,
                )
                break
            stack.extend(deps_by_task.get(node, []))
    return discrepancies



def _executable_wave(state: CollabState) -> list[dict[str, Any]]:
    """Tasks that are not terminal yet AND whose data_deps are all terminal.

    Implements wave scheduling: a task that depends on others only runs in a
    later wave once its dependencies have landed (no parallel race on deps).
    """
    terminal = _terminal_ids(state)
    results_by_id = {str(result.get("id")): result for result in state.get("results", [])}
    wave: list[dict[str, Any]] = []
    for task_dict in state.get("tasks", []):
        task_id = str(task_dict.get("id"))
        result = results_by_id.get(task_id)
        if result is not None:
            status = result.get("status")
            if status == TaskStatus.DONE.value or status == TaskStatus.BLOCKED.value:
                continue
            if status == TaskStatus.STOPPED.value:
                continue
            if status == TaskStatus.FAILED.value:
                attempts = int(result.get("attempts", 1))
                failure_type = str(result.get("failure_type", ""))
                if attempts >= MAX_TASK_RETRIES + 1 or failure_type in ("audit_invalid", "conflict", "budget_exceeded", "global_budget"):
                    continue  # hard failure or budget stop: not retryable
        deps = [str(dep) for dep in task_dict.get("data_deps", [])]
        if all(dep in terminal for dep in deps):
            wave.append(task_dict)
    return wave


def _is_retryable_failure(result: dict[str, Any]) -> bool:
    """T6: FAILED outcomes that may be retried once (failure_type-gated)."""
    if result.get("status") != TaskStatus.FAILED.value:
        return False
    if int(result.get("attempts", 1)) >= MAX_TASK_RETRIES + 1:
        return False
    failure_type = str(result.get("failure_type", ""))
    return failure_type not in ("audit_invalid", "conflict", "budget_exceeded", "global_budget")


def _route_after_arbitrate(state: CollabState):
    """After arbitration, loop back to the manager when a retryable FAILED task
    exists (manager_revise / transient); otherwise finish via collect."""
    results_by_id = {str(r.get("id")): r for r in state.get("results", [])}
    for task_dict in state.get("tasks", []):
        result = results_by_id.get(str(task_dict.get("id")))
        if result is not None and _is_retryable_failure(result):
            return "manager"
    return "collect"


def _budget_stop_node(state: CollabState) -> dict[str, Any]:
    """T6: stop every task that has not reached a terminal outcome (global cap).

    Records overspend_tokens (T6 review): the tokens consumed beyond the cap
    within the wave that tripped it - "流量控制降级为存量结算" - so the overrun
    is visible, priceable and auditable instead of a silent deficit.
    """
    terminal = _terminal_ids(state)
    token_total = int(state.get("token_total", 0))
    overspend = max(0, token_total - GLOBAL_TOKEN_BUDGET)
    stopped_results: list[dict[str, Any]] = []
    for task_dict in state.get("tasks", []):
        task_id = str(task_dict.get("id"))
        if task_id in terminal:
            continue
        stopped_results.append(
            {
                "id": task_id,
                "status": TaskStatus.STOPPED.value,
                "failure_type": "global_budget",
                "overspend_kind": "loss",
                "overspend_tokens": overspend,
                "error": "stopped by global token budget (overspend: " + str(overspend) + ")",
            }
        )
    if not stopped_results:
        return {}
    return {
        "results": stopped_results,
        "errors": ["global token budget exceeded; overspend " + str(overspend) + " tokens"],
    }


def _blocker_node(state: CollabState) -> dict[str, Any]:
    """Mark tasks whose dependencies can never become terminal (deadlock)."""
    terminal = _terminal_ids(state)
    blocked_results: list[dict[str, Any]] = []
    errors: list[str] = []
    for task_dict in state.get("tasks", []):
        task_id = str(task_dict.get("id"))
        if task_id in terminal:
            continue
        deps = [str(dep) for dep in task_dict.get("data_deps", [])]
        missing = [dep for dep in deps if dep not in terminal]
        if missing:
            blocked_results.append(
                {
                    "id": task_dict.get("id"),
                    "status": TaskStatus.BLOCKED.value,
                    "error": "dependency never terminal: " + ", ".join(missing),
                }
            )
            errors.append(
                "task " + str(task_dict.get("id"))
                + " blocked by unsatisfied dependency: " + ", ".join(missing),
            )
    if not blocked_results:
        return {}
    return {"results": blocked_results, "errors": errors}


def _route_after_manager(state: CollabState):
    """Wave dispatcher: Send next executable wave, block deadlocks, or finish.

    IMPORTANT (LangGraph Send semantics): Send branches have isolated state -
    a later branch does NOT see results/messages committed by an earlier branch.
    The manager therefore aggregates dependency outputs + incoming messages into
    each Send payload so the executor needs no cross-branch reads.
    """
    tasks = state.get("tasks", [])
    terminal = _terminal_ids(state)
    # T6 global budget: once the run exceeds the cap, stop all remaining tasks.
    if int(state.get("token_total", 0)) > GLOBAL_TOKEN_BUDGET:
        return "budget_stop"
    # Wave first: a retryable FAILED task (transient / manager_revise) is NOT
    # terminal for routing purposes - it must go back to execute_task, not collect.
    wave = _executable_wave(state)
    if wave:
        results_by_id = {str(r.get("id")): r for r in state.get("results", [])}
        messages = state.get("messages", [])
        sends: list[Send] = []
        for task_dict in wave:
            task_id = str(task_dict.get("id"))
            references: dict[str, str] = {}
            for dep_id in task_dict.get("data_deps", []):
                audit = (results_by_id.get(str(dep_id)) or {}).get("audit")
                if isinstance(audit, dict) and audit.get("output_summary"):
                    references[str(dep_id)] = str(audit["output_summary"])
            incoming = [
                str(message.get("content", ""))
                for message in messages
                if (
                    message.get("reply_to") == task_id
                    or task_id in message.get("receivers", [])
                    or task_id in message.get("references", [])
                )
            ]
            # Retry context for a previously FAILED task (manager feedback).
            prev = results_by_id.get(task_id) or {}
            retry_feedback = ""
            if prev.get("status") == TaskStatus.FAILED.value:
                retry_feedback = str(prev.get("error", "")) + " " + str(prev.get("verdict", {}).get("manager_reason", ""))
            sends.append(
                Send(
                    "execute_task",
                    {
                        "task": task_dict,
                        "context": {
                            "references": references,
                            "incoming": incoming,
                            "retry_feedback": retry_feedback.strip(),
                            "attempts": int(prev.get("attempts", 0)) + 1,
                            "task_token_total": int(prev.get("task_token_total", 0)),
                        },
                    },
                )
            )
        return sends
    # Wave empty: if every task reached a terminal outcome we are done, otherwise
    # the remaining non-terminal tasks have unsatisfiable dependencies (block).
    all_terminal = all(str(task_dict.get("id")) in terminal for task_dict in tasks)
    return "collect" if all_terminal else "blocker"

def _arbitration_node_factory(
    llm: Any,
    *,
    root_dir: Any = None,
    memory_store: Any = None,
    audit_llm: Any = None,
    light: bool = False,
) -> Callable[[CollabState], dict[str, Any]]:
    """Build the arbitration node: hard rules + manager provisional for each
    DONE task without a verdict yet. Failing tasks are marked FAILED with the
    reason; results merge by id so a revised outcome replaces the original."""
    def arbitration_node(state: CollabState) -> dict[str, Any]:
        tasks = state.get("tasks", [])
        results = state.get("results", [])
        updated: list[dict[str, Any]] = []
        for result in results:
            if result.get("status") != TaskStatus.DONE.value or result.get("verdict") is not None:
                continue
            task_dict = next((t for t in tasks if str(t.get("id")) == str(result.get("id"))), None)
            if task_dict is None:
                continue
            task = Task.from_dict(task_dict)
            audit_data = result.get("audit")
            if isinstance(audit_data, dict):
                audit = TaskAudit(
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
                )
            else:
                audit = None
            # Cross-task anchors: dependency audit snapshots (independently
            # checkable), per the T4 review confidence requirement.
            snapshot_ids: list[str] = []
            for dep_id in task.data_deps:
                dep_result = next((x for x in results if str(x.get("id")) == str(dep_id)), None)
                dep_audit = (dep_result or {}).get("audit")
                if isinstance(dep_audit, dict):
                    snapshot_ids.append(str(dep_audit.get("input_snapshot", dep_id)[:24]))
            hard = hard_rules_check(task, audit, snapshot_ids=snapshot_ids)
            if light:
                manager, manager_reason = "pass", "轻量模式：跳过经理裁决（仅硬规则）"
            else:
                manager, manager_reason = manager_arbitrate(audit_llm or llm, task, audit, root_dir=root_dir)
            ok = hard.ok and manager == "pass"
            verdict = {
                "task_id": task.id,
                "ok": ok,
                "reasons": list(hard.reasons),
                "conflicts": [c.to_dict() for c in hard.conflicts],
                "coverage": hard.coverage.to_dict() if hard.coverage else None,
                "manager": manager,
                "manager_reason": manager_reason,
                "failure_type": "manager_revise" if manager == "revise" else hard.failure_type,
            }
            updated_result = dict(result)
            updated_result["verdict"] = verdict
            if not ok:
                updated_result["status"] = TaskStatus.FAILED.value
                reasons = list(hard.reasons)
                if manager == "revise":
                    reasons.append("经理裁决: " + manager_reason)
                updated_result["error"] = "; ".join(reasons) if reasons else "arbitration rejected"
            if manager == "revise":
                updated_result["failure_type"] = "manager_revise"
            # T8: write memory only after the task's arbitration passed (verdict.ok),
            # so a soon-to-be-REVISE output is never persisted as a cross-run memory.
            if ok and memory_store is not None:
                for mem in memory_entries_from_output(task, audit, snapshot_ids=snapshot_ids):
                    memory_store.add(mem)
            updated.append(updated_result)
        return {"results": updated}

    return arbitration_node


def _collect_node(state: CollabState) -> dict[str, Any]:
    """Once every task is terminal, emit the collaboration report."""
    tasks = state.get("tasks", [])
    results = state.get("results", [])
    if not tasks:
        return {"final_report": "协作未包含任何任务。"}
    by_id = {r.get("id"): r for r in results}
    pending_ids = [
        t.get("id") for t in tasks
        if by_id.get(t.get("id"), {}).get("status") not in RUN_TERMINAL_STATUSES
    ]
    if pending_ids:
        return {}
    # Roundtable T3 review #2: verify BLOCKED labels via dependency-closure walk.
    discrepancies = _verify_blocked_reachability(tasks, results)
    errors = list(state.get("errors", []))
    if discrepancies:
        errors.extend("BLOCKED discrepancy: " + d for d in discrepancies)
    report = _build_collab_report(
        tasks, by_id,
        token_total=state.get("token_total", 0),
        attempts=state.get("attempts", []),
        mode=state.get("mode", "wave"),
        experimental=state.get("experimental", False),
        parallel_note=state.get("parallel_note", ""),
    )
    if discrepancies:
        report += "\n\n## BLOCKED 复核异常\n- " + "\n- ".join(discrepancies)
    return {"final_report": report, "errors": errors}


def _build_collab_report(
    tasks: list[dict[str, Any]],
    results: dict[str, dict[str, Any]],
    *,
    token_total: int,
    attempts: list[dict[str, Any]] | None = None,
    mode: str = "wave",
    experimental: bool = False,
    parallel_note: str = "",
) -> str:
    """Summarise the run: per-task status, audited output, citations, totals."""
    lines = ["# 协作执行报告", "", "- 任务数: %d" % len(tasks), "- Token 总消耗: %d" % token_total]
    lines.append("- 模式: " + mode + ("（experimental）" if experimental else ""))
    if parallel_note:
        lines.append("- 说明: " + parallel_note)
    cost = cost_summary(list(results.values()))
    if cost["total_usd"] > 0:
        lines.append("- 成本(USD): $%.4f" % cost["total_usd"])
        if cost["estimated_usd"] > 0:
            lines.append("- 其中估算成本(USD): $%.4f" % cost["estimated_usd"])
        by_persona = {k: "%.4f" % v for k, v in sorted(cost["per_persona"].items())}
        lines.append("- 成本按 Persona: " + "；".join(k + "=$" + v for k, v in by_persona.items()))
        est_persona = {k: "%.4f" % v for k, v in sorted(cost["estimated_persona"].items())}
        if est_persona:
            lines.append("- 其中估算按 Persona: " + "；".join(k + "=$" + v for k, v in est_persona.items()))
    mem = memory_summary(list(results.values()))
    if mem["memory_tokens"] > 0:
        lines.append("- 记忆开销(USD): $%.4f（%d token，占总成本 %.3f）" % (mem["memory_cost_usd"], mem["memory_tokens"], mem["memory_share"]))
    waste = waste_breakdown(list(results.values()), attempts or [])
    if waste["waste_cost_usd"] > 0 or waste["waste_tokens"] > 0:
        lines.append("- 损耗(USD): $%.4f" % waste["waste_cost_usd"])
        lines.append("- 损耗 Token: %d" % waste["waste_tokens"])
        if waste["waste_reasons"]:
            reasons = ["%s:%s($%.4f)" % (r["id"], r["failure_type"], r["cost_usd"]) for r in waste["waste_reasons"]]
            lines.append("- 损耗原因: " + "；".join(reasons))
    fb = feedback_summary(attempts or [], list(results.values()))
    if fb["tasks_that_retried"] > 0:
        rr = fb["recovery_rate"]
        rr_text = ("%.3f" % rr) if rr is not None else "N/A"
        lines.append("- 重试恢复: %d/%d (recovery %s)" % (fb["retries_that_succeeded"], fb["tasks_that_retried"], rr_text))
    # T12: soft-budget warning + overspend responsibility + per-persona rep (exposed, not gated).
    soft_warn_count = sum(1 for r in results.values() if isinstance(r, dict) and r.get("soft_budget_warning"))
    if soft_warn_count:
        lines.append("- 软上限预警任务数: %d" % soft_warn_count)
    if token_total > GLOBAL_BUDGET_SOFT:
        lines.append("- 全局预算预警: 已超过软上限(%.0f%% of %d)" % (GLOBAL_BUDGET_SOFT / GLOBAL_TOKEN_BUDGET * 100, GLOBAL_TOKEN_BUDGET))
    debt = sum(1 for r in results.values() if isinstance(r, dict) and r.get("overspend_kind") == "debt")
    loss = sum(1 for r in results.values() if isinstance(r, dict) and r.get("overspend_kind") == "loss")
    if debt or loss:
        lines.append("- 超支责任: debt=%d; loss=%d" % (debt, loss))
    rep = rep_by_persona(list(results.values()), attempts or [])
    if rep:
        lines.append("- Persona 信誉(有效/总成本): " + "；".join(k + "=%.2f" % v for k, v in sorted(rep.items())))
    lines.append("")
    lines.append("## 任务结果")
    for task_dict in tasks:
        task_id = str(task_dict.get("id"))
        result = results.get(task_id, {})
        status = str(result.get("status", "missing"))
        lines.append("")
        lines.append("### " + task_id + "（" + str(task_dict.get("persona_id")) + "）— " + status)
        audit = result.get("audit")
        if isinstance(audit, dict):
            lines.append(audit.get("output_summary", ""))
        elif result.get("error"):
            lines.append("错误: " + str(result["error"]))
        else:
            lines.append("无产出记录")
    return "\n".join(lines)


def build_collab_graph(
    llm: Any,
    *,
    root_dir: Any = None,
    memory_store: Any = None,
    audit_llm: Any = None,
    light: bool = False,
) -> Any:
    """Compile the mode-B execution graph.

    Args:
        llm: an LLMClient (mock or real) used by every task branch.
        root_dir: repo root for persona lookup (default: project root).
    Returns:
        A compiled LangGraph StateGraph ready for ``invoke``.
    """
    builder = StateGraph(CollabState)
    builder.add_node("manager", _manager_node)
    builder.add_node("execute_task", _executor_node_factory(llm, root_dir=root_dir, memory_store=memory_store))
    builder.add_node("blocker", _blocker_node)
    builder.add_node("budget_stop", _budget_stop_node)
    builder.add_node("arbitrate", _arbitration_node_factory(llm, root_dir=root_dir, memory_store=memory_store, audit_llm=audit_llm, light=light))
    builder.add_node("collect", _collect_node)
    builder.add_edge(START, "manager")
    builder.add_conditional_edges(
        "manager",
        _route_after_manager,
        {
            "execute_task": "execute_task",
            "collect": "arbitrate",
            "blocker": "blocker",
            "budget_stop": "budget_stop",
        },
    )
    # Wave loop: after each wave, return to the manager to dispatch the next one.
    builder.add_edge("execute_task", "manager")
    builder.add_edge("blocker", "collect")
    builder.add_edge("budget_stop", "collect")
    # Arbitration runs once all tasks are terminal, then collect writes the report.
    builder.add_conditional_edges(
        "arbitrate",
        _route_after_arbitrate,
        {"manager": "manager", "collect": "collect"},
    )
    builder.add_edge("collect", END)
    return builder.compile()


def run_collab_sync(
    tasks: list[Task],
    *,
    provider: str = "auto",
    mock: bool = False,
    root_dir: Any = None,
    memory_store: Any = None,
    mode: str = "wave",
    audit_llm: Any = None,
    light: bool = False,
) -> dict[str, Any]:
    """Synchronous convenience entry (T7 will wrap this async).

    Builds an LLM from provider/mock, compiles the graph, invokes it with the
    given tasks, and returns the terminal state (tasks/results/report). mode is
    "wave" (default) or "parallel" (experimental; only when all tasks have no
    data_deps - the report is marked experimental otherwise it falls back).
    """
    if not tasks:
        raise ValueError("tasks must not be empty")
    task_dicts = [task.to_dict() for task in tasks]
    eff_mode, experimental, parallel_note = resolve_mode(task_dicts, mode)
    llm = resolve_llm("mock" if mock else provider, root_dir=root_dir)
    app = build_collab_graph(llm, root_dir=root_dir, memory_store=memory_store, audit_llm=audit_llm, light=light)
    initial: CollabState = {
        "tasks": task_dicts,
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
        "attempts": [],
        "mode": eff_mode,
        "experimental": experimental,
        "parallel_note": parallel_note,
    }
    return app.invoke(initial)


__all__ = [
    "CollabState",
    "build_collab_graph",
    "run_collab_sync",
]