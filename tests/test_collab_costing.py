"""T10 tests: token->cost pricing, unknown-provider estimation, per-persona cost
aggregation, and wiring cost/persona into the audit + report.
"""

from __future__ import annotations

from pathlib import Path

from collab.costing import cost_by_persona, cost_summary, is_estimated, memory_summary, price_tokens
from collab.graph import build_collab_graph
from collab.models import Task

ROOT = Path(__file__).resolve().parent.parent


class CostCaptureLLM:
    provider_name = "openai"
    model = "gpt-4o-mini"
    last_usage = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}

    def generate(self, prompt: str) -> str:
        return "采用方案A，理由：成本可控。"


def _task(task_id: str, persona: str, input_text: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id=persona, input=input_text, **kwargs)


def test_price_tokens_known_provider():
    # deepseek rates 0.00014/0.00028 per 1K.
    cost = price_tokens("deepseek", "deepseek-chat", 1000, 500)
    assert abs(cost - 0.00028) < 1e-9
    assert is_estimated("deepseek") is False


def test_price_tokens_unknown_provider_is_estimated():
    cost = price_tokens("some-vendor", "x", 1000, 0)
    # falls back to conservative default 0.0002/1K input
    assert abs(cost - 0.0002) < 1e-9
    assert is_estimated("some-vendor") is True


def test_price_tokens_mock_free():
    assert price_tokens("mock", "mock", 1000, 1000) == 0.0
    assert is_estimated("mock") is False


def test_cost_by_persona_aggregates():
    results = [
        {"audit": {"persona_id": "computing", "cost_usd": 0.001}},
        {"audit": {"persona_id": "history", "cost_usd": 0.002}},
        {"audit": {"persona_id": "computing", "cost_usd": 0.0005}},
        {"audit": None},
    ]
    by_persona = cost_by_persona(results)
    assert abs(by_persona["computing"] - 0.0015) < 1e-6
    assert abs(by_persona["history"] - 0.002) < 1e-6
    assert "unknown" not in by_persona  # None audit skipped


def test_price_tokens_model_override():
    pricing = {"deepseek:reasoner": (0.0005, 0.0015)}
    cost = price_tokens("deepseek", "reasoner", 1000, 1000, pricing=pricing)
    assert abs(cost - 0.002) < 1e-9
    assert is_estimated("deepseek", "reasoner", pricing=pricing) is False


def test_cost_summary_split_priced_estimated():
    results = [
        {"audit": {"persona_id": "computing", "cost_usd": 0.003, "provider": "openai", "model": "gpt-4o-mini"}},
        {"audit": {"persona_id": "history", "cost_usd": 0.002, "provider": "unknown-vendor", "model": "x"}},
    ]
    s = cost_summary(results)
    assert abs(s["total_usd"] - 0.005) < 1e-6
    assert abs(s["priced_usd"] - 0.003) < 1e-6
    assert abs(s["estimated_usd"] - 0.002) < 1e-6
    assert s["estimated_persona"] == {"history": 0.002}


def test_cost_summary():
    results = [{"audit": {"persona_id": "computing", "cost_usd": 0.003}}]
    s = cost_summary(results)
    assert abs(s["total_usd"] - 0.003) < 1e-6
    assert s["per_persona"] == {"computing": 0.003}


def test_executor_writes_cost_and_persona_into_audit_and_report():
    llm = CostCaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT)
    task = _task("t-001", "computing", "估算方案成本", expected_output="给出方案")
    state = app.invoke(
        {
            "tasks": [task.to_dict()],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
        }
    )
    results = {r["id"]: r for r in state["results"]}
    assert results["t-001"]["status"] == "done"
    audit = results["t-001"]["audit"]
    assert audit["prompt_tokens"] == 1000
    assert audit["completion_tokens"] == 500
    assert audit["provider"] == "openai"
    assert audit["model"] == "gpt-4o-mini"
    assert audit["persona_id"] == "computing"
    assert audit["cost_usd"] > 0
    report = state["final_report"]
    assert "成本(USD)" in report
    assert "computing=$" in report


def test_memory_summary_is_subset_not_addition():
    results = [
        {"audit": {"persona_id": "computing", "cost_usd": 0.003, "provider": "openai", "model": "gpt-4o-mini", "memory_tokens": 300}},
        {"audit": {"persona_id": "history", "cost_usd": 0.002, "provider": "openai", "model": "gpt-4o-mini", "memory_tokens": 0}},
    ]
    m = memory_summary(results)
    assert m["memory_tokens"] == 300
    # openai input rate 0.00015/1K -> 300 * 0.00015 / 1000
    assert abs(m["memory_cost_usd"] - 0.000045) < 1e-9
    assert abs(m["memory_share"] - 0.000045 / 0.005) < 1e-9


def test_memory_summary_skips_missing_audit():
    m = memory_summary([{"audit": None}, {"audit": {"cost_usd": 0.001}}])
    assert m["memory_tokens"] == 0
    assert m["memory_cost_usd"] == 0
    assert m["memory_share"] == 0


def test_executor_writes_memory_tokens_into_audit_and_report(tmp_path: Path):
    from collab.memory import MemoryEntry, MemoryStore

    store = MemoryStore(tmp_path / "mem.db")
    store.add(MemoryEntry(agent_id="computing", content="历史结论：采用方案A", tags=["方案", "成本"]))
    llm = CostCaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT, memory_store=store)
    state = app.invoke(
        {
            "tasks": [_task("t-001", "computing", "估算方案成本", expected_output="给出方案").to_dict()],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
        }
    )
    results = {r["id"]: r for r in state["results"]}
    audit = results["t-001"]["audit"]
    assert audit["memory_tokens"] > 0
    assert "记忆开销(USD)" in state["final_report"]
