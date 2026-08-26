"""T23 (FR-GAP-5): FR-META adversarial verification.

These cases deliberately inject faults into the collaboration engine and assert
the engine exposes and corrects them (audit hard rules, arbitration rejection,
memory governance, budget enforcement, crash recovery, cost sub-accounting).

Adversarial principle: manufacture an error the system should NOT silently
accept - then assert it is surfaced (verdict/status/reason) or corrected.
"""

from __future__ import annotations

from pathlib import Path

from collab.arbitration import detect_decision_conflicts, hard_rules_check
from collab.audit import build_audit
from collab.costing import cost_summary, memory_summary
from collab.graph import _arbitration_node_factory, build_collab_graph
from collab.memory import MemoryEntry, MemoryStore
from collab.models import Task, TaskAudit
from collab.runner import get_collab_status
from collab.runstore import RunStore

ROOT = Path(__file__).resolve().parent.parent
_SUMMARY = "- 引用输入快照: snap-001\n- 关键决策点: 1) 采用A\n- 任务结论: x"


def _audit(*, summary: str, reasoning: str = "展开推理", snapshot: str = "snap-001", cost: float = 0.001):
    return TaskAudit(
        input_snapshot=snapshot,
        output_summary=summary,
        output_reasoning=reasoning,
        token_usage=100,
        prompt_tokens=80,
        completion_tokens=20,
        provider="mock",
        model="mock",
        cost_usd=cost,
        persona_id="computing",
    )


def test_adversarial_invalid_audit_caught_by_hard_rules():
    task = Task(id="t1", persona_id="computing", input="x", expected_output="y")
    audit = _audit(summary="只有一段结论，没有结构化字段")
    verdict = hard_rules_check(task, audit)
    assert verdict.ok is False
    assert verdict.failure_type == "audit_invalid"
    assert any("missing required field" in r for r in verdict.reasons)


def test_adversarial_self_contradiction_caught():
    task = Task(id="t1", persona_id="computing", input="x", expected_output="y")
    audit = _audit(summary="- 关键决策点: 1) 采用方案A; 2) 放弃方案A", reasoning="采用方案A")
    conflicts = detect_decision_conflicts(audit.output_summary, audit.output_reasoning)
    assert conflicts, "explicit verb/object contradiction must be detected"
    verdict = hard_rules_check(task, audit)
    assert verdict.ok is False
    assert "显性决策矛盾" in "; ".join(verdict.reasons)


def test_adversarial_negative_cost_rejected_by_build_audit():
    try:
        build_audit(
            input_snapshot="snap-001",
            output_summary=_SUMMARY,
            output_reasoning="r",
            token_usage=100,
            cost_usd=-0.5,
        )
        assert False, "build_audit must reject a negative cost"
    except ValueError:
        pass


def test_adversarial_unprovenanced_fact_rejected():
    try:
        MemoryEntry(agent_id="computing", content="这是一个事实", kind="fact")
        assert False, "a fact without provenance must be rejected"
    except ValueError:
        pass


def test_adversarial_revise_never_writes_memory(tmp_path: Path):
    class ReviseLlm:
        provider_name = "mock"
        model = "mock"
        last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

        def generate(self, prompt: str) -> str:
            return "REVISE 不满足任务意图"

    store = MemoryStore(tmp_path / "adv_revise.db")
    node = _arbitration_node_factory(ReviseLlm(), memory_store=store)
    task = Task(id="t1", persona_id="computing", input="x", expected_output="y")
    audit = _audit(summary=_SUMMARY)
    state = {
        "tasks": [task.to_dict()],
        "results": [{"id": "t1", "status": "done", "audit": audit.to_dict()}],
    }
    out = node(state)
    res = out["results"][0]
    assert res["verdict"]["ok"] is False
    assert res["verdict"]["failure_type"] == "manager_revise"
    assert store.list("computing") == []


def test_adversarial_weak_contradiction_cannot_erase_strong_memory(tmp_path: Path):
    store = MemoryStore(tmp_path / "adv_gov.db")
    strong = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", kind="judgment", confidence=0.9))
    weak = store.add(MemoryEntry(agent_id="computing", content="决策点: 放弃方案A", kind="judgment", confidence=0.1))
    assert store.get("computing", strong.id).status == "active"
    assert store.get("computing", weak.id).status == "overridden"


def test_adversarial_task_over_budget_fails_loudly():
    class BudgetLlm:
        provider_name = "mock"
        model = "mock"
        last_usage = {"prompt_tokens": 1000, "completion_tokens": 0, "total_tokens": 1000}

        def generate(self, prompt: str) -> str:
            return "产出"

    app = build_collab_graph(BudgetLlm(), root_dir=ROOT)
    task = Task(id="t-001", persona_id="computing", input="x", expected_output="", budget_tokens=500)
    state = app.invoke(
        {"tasks": [task.to_dict()], "results": [], "messages": [], "token_total": 0, "errors": []}
    )
    res = next(r for r in state["results"] if r["id"] == "t-001")
    assert res["status"] == "failed"
    assert res["failure_type"] == "budget_exceeded"


def test_adversarial_orphan_run_not_stuck_running(tmp_path: Path):
    from datetime import datetime, timedelta, timezone
    store = RunStore(tmp_path / "runs.db")
    old = (datetime.now(timezone.utc) - timedelta(seconds=1000)).isoformat(timespec="seconds")
    store.save({
        "run_id": "r-orph", "status": "running", "created_at": old,
        "finished_at": None, "stop_reason": None, "provider": "mock", "mock": True,
        "summary": {"run_id": "r-orph", "status": "running"},
    })
    st = get_collab_status("r-orph", run_store=store)
    assert st["status"] == "failed"
    assert "crashed" in st["stop_reason"]


def test_adversarial_memory_cost_is_subset_not_double_count():
    results = [
        {"audit": {"persona_id": "computing", "cost_usd": 0.01, "provider": "openai", "model": "gpt-4o-mini", "memory_tokens": 200}},
        {"audit": {"persona_id": "history", "cost_usd": 0.005, "provider": "openai", "model": "gpt-4o-mini", "memory_tokens": 0}},
    ]
    total = cost_summary(results)["total_usd"]
    mem = memory_summary(results)
    assert abs(total - 0.015) < 1e-9
    assert mem["memory_cost_usd"] > 0 and mem["memory_cost_usd"] < total
    assert 0 <= mem["memory_share"] <= 1
