"""V2 collaboration engine: async runner entry (T7).

Provides the M1 entry points that M3 will expose as MCP tools:

    run_collaboration(tasks, *, provider, mock, root_dir) -> run_id
        starts the collaboration on a background thread and returns a run id
        immediately (the graph itself stays synchronous in run_collab_sync).
    get_collab_status(run_id) -> dict
        polls the run: running/done/failed plus result summary (incl.
        overspend accounting from T6).
    stop_collab(run_id, reason) -> dict
        soft-stop: marks the run stopped; the report then records the reason.

Overspend responsibility (T6 review): the entry records overspend_tokens on
the run, and the final report states that the overrun is a wave-boundary
execution cost (parallel tasks cannot be interrupted mid-flight) - it is
accounted, not silently absorbed, and future pricing can use the real cost.
See docs/AGENT_GUIDE.md section 3.2.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .costing import cost_summary, feedback_summary, memory_summary, waste_breakdown
from .graph import run_collab_sync
from .models import Task
from .runstore import RunStore

_RUNS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

_HEARTBEAT_INTERVAL_SECONDS = 10  # T22 heartbeat cadence


def _new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def _task_from_spec(spec: dict[str, Any]) -> Task:
    """Build a Task from a caller-provided definition dict (validation)."""
    required = ("id", "persona_id", "input")
    missing = [key for key in required if not str(spec.get(key, "")).strip()]
    if missing:
        raise ValueError("task spec missing required keys: " + ", ".join(missing))
    return Task.from_dict(spec)


def run_collaboration(
    tasks: list[dict[str, Any]],
    *,
    provider: str = "auto",
    mock: bool = False,
    root_dir: Any = None,
    run_store: RunStore | None = None,
    mode: str = "wave",
    memory_store: Any = None,
    audit_llm: Any = None,
    light: bool = False,
) -> str:
    """Start a collaboration on a background thread and return its run id.

    The caller polls with get_collab_status(run_id). M1 storage is in-memory;
    M2 (T16) optionally persists the run *summary* via the RunStore so history
    survives a restart. M3/CLI drives this via run + status/report (the company
    workflow entry, NOT an MCP server).
    """
    if not tasks:
        raise ValueError("tasks must not be empty")
    parsed = [_task_from_spec(spec) for spec in tasks]
    run_id = _new_run_id()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "created_at": created,
        "finished_at": None,
        "stop_reason": None,
        "provider": provider,
        "mock": mock,
        "state": None,
        "error": None,
    }
    with _LOCK:
        _RUNS[run_id] = record
    if run_store is not None:
        run_store.save({
            "run_id": run_id,
            "status": "running",
            "created_at": created,
            "finished_at": None,
            "stop_reason": None,
            "provider": provider,
            "mock": mock,
            "last_heartbeat": created,
            "summary": {"run_id": run_id, "status": "running", "created_at": created},
        })

    _hb_stop = threading.Event()

    def _heartbeat() -> None:
        while not _hb_stop.wait(_HEARTBEAT_INTERVAL_SECONDS):
            try:
                run_store.touch(run_id)
            except Exception:
                pass

    def _worker() -> None:
        try:
            state = run_collab_sync(parsed, provider=provider, mock=mock, root_dir=root_dir, mode=mode, memory_store=memory_store, audit_llm=audit_llm, light=light)
            with _LOCK:
                current = _RUNS.get(run_id)
                if current is None:
                    return
                current["state"] = state
                # A soft-stop must survive the worker finishing (otherwise the
                # thread would overwrite stopped back to done).
                if current.get("stop_reason"):
                    current["status"] = "stopped"
                else:
                    current["status"] = "done"
                current["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if run_store is not None:
                    run_store.save({
                        "run_id": run_id,
                        "status": current["status"],
                        "created_at": current["created_at"],
                        "finished_at": current["finished_at"],
                        "stop_reason": current["stop_reason"],
                        "provider": provider,
                        "mock": mock,
                        "summary": _build_summary(current),
                    })
        except Exception as exc:
            with _LOCK:
                current = _RUNS.get(run_id)
                if current is None:
                    return
                current["status"] = "failed"
                current["error"] = str(exc)
                current["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                if run_store is not None:
                    run_store.save({
                        "run_id": run_id,
                        "status": current["status"],
                        "created_at": current["created_at"],
                        "finished_at": current["finished_at"],
                        "stop_reason": current["stop_reason"],
                        "provider": provider,
                        "mock": mock,
                        "summary": _build_summary(current),
                    })
        finally:
            _hb_stop.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    if run_store is not None:
        threading.Thread(target=_heartbeat, daemon=True).start()
    return run_id


def _build_summary(record: dict[str, Any]) -> dict[str, Any]:
    """Build the compact run summary (digest, not full graph state)."""
    summary: dict[str, Any] = {
        "run_id": record.get("run_id"),
        "status": record.get("status", "running"),
        "created_at": record.get("created_at"),
        "finished_at": record.get("finished_at"),
        "stop_reason": record.get("stop_reason"),
        "error": record.get("error"),
    }
    state = record.get("state")
    if state is not None:
        summary["task_count"] = len(state.get("tasks", []))
        summary["results"] = [
            {
                "id": r.get("id"),
                "status": r.get("status"),
                "failure_type": r.get("failure_type", ""),
            }
            for r in state.get("results", [])
        ]
        summary["token_total"] = state.get("token_total", 0)
        summary["overspend_tokens"] = _overspend_of(state)
        summary["final_report"] = state.get("final_report", "")
        # T19: cost / waste / recovery (reuse the costing helpers).
        results = state.get("results", [])
        attempts = state.get("attempts", [])
        cost = cost_summary(results)
        if cost["total_usd"] > 0:
            summary["cost_usd"] = cost["total_usd"]
            summary["cost_priced_usd"] = cost["priced_usd"]
            summary["cost_estimated_usd"] = cost["estimated_usd"]
            summary["cost_by_persona"] = cost["per_persona"]
        mem = memory_summary(results)
        if mem["memory_tokens"] > 0:
            summary["memory_tokens"] = mem["memory_tokens"]
            summary["memory_cost_usd"] = mem["memory_cost_usd"]
            summary["memory_share"] = mem["memory_share"]
        waste = waste_breakdown(results, attempts)
        if waste["waste_cost_usd"] > 0 or waste["waste_tokens"] > 0:
            summary["waste_cost_usd"] = waste["waste_cost_usd"]
            summary["waste_tokens"] = waste["waste_tokens"]
            summary["waste_reasons"] = waste["waste_reasons"]
        fb = feedback_summary(attempts, results)
        if fb["tasks_that_retried"] > 0:
            summary["retries_that_succeeded"] = fb["retries_that_succeeded"]
            summary["tasks_that_retried"] = fb["tasks_that_retried"]
            summary["recovery_rate"] = fb["recovery_rate"]
    return summary


def get_collab_status(run_id: str, *, run_store: RunStore | None = None) -> dict[str, Any]:
    """Return the current status and (once done) the result summary.

    Live runs come from memory; a run this process does not know (e.g. from a
    previous run after restart) is looked up in the optional persisted RunStore.
    """
    with _LOCK:
        record = _RUNS.get(run_id)
    if record is not None:
        return _build_summary(record)
    if run_store is not None:
        stored = run_store.get(run_id)
        if stored is not None:
            base = {
                "run_id": run_id,
                "status": stored["status"],
                "created_at": stored["created_at"],
                "finished_at": stored["finished_at"],
                "stop_reason": stored["stop_reason"],
            }
            base.update(stored["summary"])
            # The persisted row is authoritative over the (possibly stale) digest's
            # status/finished_at/stop_reason - a normalised crashed run must show
            # as failed even if its stored summary still says "running".
            base["status"] = stored["status"]
            base["finished_at"] = stored["finished_at"]
            base["stop_reason"] = stored["stop_reason"]
            return base
    return {"run_id": run_id, "status": "not_found", "error": "unknown run id"}


def _overspend_of(state: dict[str, Any]) -> int:
    """T6 overspend accounting: sum overspend_tokens recorded on stopped tasks."""
    total = 0
    for result in state.get("results", []):
        if result.get("failure_type") == "global_budget":
            total = max(total, int(result.get("overspend_tokens", 0)))
    return total


def stop_collab(run_id: str, reason: str = "user requested") -> dict[str, Any]:
    """Soft-stop: mark the run stopped with a reason.

    M1 semantics: LangGraph invoke on the worker thread cannot be force-killed;
    the stop is recorded and surfaced in the final status so the caller can
    treat the run as cancelled. Hard cancellation is a M2 concern.
    """
    with _LOCK:
        record = _RUNS.get(run_id)
        if record is None:
            return {"run_id": run_id, "ok": False, "error": "unknown run id"}
        if record["status"] in ("done", "failed"):
            return {"run_id": run_id, "ok": False, "error": "run already finished: " + record["status"]}
        record["stop_reason"] = reason
        record["status"] = "stopped"
        return {"run_id": run_id, "ok": True, "stop_reason": reason}


def list_collab_runs(*, run_store: RunStore | None = None) -> list[dict[str, Any]]:
    """List runs (newest first); live memory + optional persisted history."""
    merged: dict[str, dict[str, Any]] = {}
    if run_store is not None:
        for r in run_store.list():
            merged[str(r["run_id"])] = {"run_id": str(r["run_id"]), "status": str(r["status"]), "created_at": str(r["created_at"])}
    with _LOCK:
        for rid, r in _RUNS.items():
            merged[str(rid)] = {"run_id": str(rid), "status": r["status"], "created_at": r["created_at"]}
    runs = list(merged.values())
    runs.sort(key=lambda item: item["created_at"], reverse=True)
    return runs


__all__ = [
    "get_collab_status",
    "list_collab_runs",
    "run_collaboration",
    "stop_collab",
]
