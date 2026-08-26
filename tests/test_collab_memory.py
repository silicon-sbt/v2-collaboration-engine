"""Tests for the V2 per-agent memory module (T8): partition, Top-K keyword
retrieval, cross-run persistence, prompt injection, and write-after-arbitration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from collab.memory import (
    MemoryEntry,
    MemoryStore,
    build_memory_context,
    memory_entries_from_output,
)
from collab.graph import build_collab_graph
from collab.models import Task

ROOT = Path(__file__).resolve().parent.parent


class _TaskAudit:
    def __init__(self, summary: str) -> None:
        self.output_summary = summary


class _TaskLite:
    def __init__(self, persona_id: str, task_id: str) -> None:
        self.persona_id = persona_id
        self.id = task_id


class CaptureLLM:
    """LLM that records every prompt it is given (for injection assertions)."""

    provider_name = "capture"
    model = "capture"
    last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "采用方案A。理由：B 更稳。"


def _task(task_id: str, persona: str, input_text: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id=persona, input=input_text, **kwargs)


# --- store primitives -------------------------------------------------------


def test_add_get_list(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    entry = MemoryEntry(agent_id="computing", content="符号计算很有价值", tags=["decision"])
    store.add(entry)
    got = store.get("computing", entry.id)
    assert got is not None
    assert got.content == entry.content
    assert got.kind == "judgment"
    assert [e.content for e in store.list("computing")] == ["符号计算很有价值"]


def test_search_ranks_relevant_and_excludes_stale(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    store.add(MemoryEntry(agent_id="computing", content="符号计算在推理中很关键", tags=["推理"]))
    store.add(MemoryEntry(agent_id="computing", content="关于制度的一些泛泛看法", tags=["制度"]))
    store.add(MemoryEntry(agent_id="history", content="符号计算历史视角", tags=["推理"]))
    hits = store.search("computing", "符号计算 推理")
    assert hits, "expected at least one lexical hit"
    assert hits[0].content == "符号计算在推理中很关键"
    # stale is hidden by default
    stale = store.add(MemoryEntry(agent_id="computing", content="过期判断", tags=["推理"]))
    store.mark_stale("computing", stale.id)
    assert all(e.content != "过期判断" for e in store.search("computing", "符号计算 推理"))
    assert any(e.content == "过期判断" for e in store.list("computing", include_stale=True))


def test_cross_instance_persistence(tmp_path: Path):
    db = tmp_path / "mem.db"
    store = MemoryStore(db)
    store.add(MemoryEntry(agent_id="computing", content="跨 run 持久记忆", tags=["持久"]))
    fresh = MemoryStore(db)
    assert [e.content for e in fresh.list("computing")] == ["跨 run 持久记忆"]


def test_mark_stale(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    entry = store.add(MemoryEntry(agent_id="computing", content="待废弃"))
    store.mark_stale("computing", entry.id)
    assert store.get("computing", entry.id).status == "stale"
    assert len(store.list("computing")) == 0


def test_fact_memory_requires_provenance():
    with pytest.raises(ValueError):
        MemoryEntry(agent_id="computing", content="待核验", kind="fact")
    # With an independently checkable provenance it is allowed.
    entry = MemoryEntry(agent_id="computing", content="已核验", kind="fact", provenance="snap-1")
    assert entry.kind == "fact" and entry.provenance == "snap-1"


# --- context + extraction ---------------------------------------------------


def test_build_memory_context_marks_boundary():
    entries = [
        MemoryEntry(agent_id="computing", content="事实A", kind="fact", source="t-1", provenance="t-1"),
        MemoryEntry(agent_id="computing", content="判断B"),
    ]
    ctx = build_memory_context(entries)
    assert "（记忆）" in ctx
    assert "（记忆结束）" in ctx
    assert "已核验事实" in ctx
    assert "既往判断" in ctx


def test_memory_entries_from_output_extracts_judgments():
    audit = _TaskAudit("- 关键决策点: 1) 采用符号计算; 2) 证明可行\n- 任务结论: 可行")
    task = _TaskLite("computing", "t-1")
    entries = memory_entries_from_output(task, audit)
    contents = [e.content for e in entries]
    assert any("采用符号计算" in c for c in contents)
    assert any("结论: 可行" in c for c in contents)
    assert all(e.agent_id == "computing" for e in entries)
    assert all(e.provenance == "t-1" for e in entries)


# --- graph integration ------------------------------------------------------


def test_run_injects_memory_into_prompt(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    store.add(MemoryEntry(agent_id="computing", content="符号计算是关键变量", tags=["推理"]))
    llm = CaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT, memory_store=store)
    task = _task("t-001", "computing", "评估符号计算对推理的影响")
    state = app.invoke(
        {
            "tasks": [task.to_dict()],
            "results": [],
            "messages": [],
            "token_total": 0,
            "errors": [],
        }
    )
    assert llm.prompts, "executor should have produced a prompt"
    assert "符号计算是关键变量" in llm.prompts[0]
    assert "（记忆）" in llm.prompts[0]


def test_writes_memory_after_arbitration_passes(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    llm = CaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT, memory_store=store)
    task = _task("t-001", "computing", "给出方案", expected_output="给出一个方案")
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
    memories = store.list("computing")
    assert memories, "a passed task should write memory"
    joined = " ".join(m.content for m in memories)
    assert "采用方案A" in joined


def test_no_memory_store_writes_nothing(tmp_path: Path):
    llm = CaptureLLM()
    app = build_collab_graph(llm, root_dir=ROOT, memory_store=None)
    task = _task("t-001", "computing", "evaluate", expected_output="out")
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


def test_search_min_score_gate_no_strong_hit_no_injection(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    store.add(MemoryEntry(agent_id="computing", content="符号计算在推理中很关键", tags=["推理"]))
    hits = store.search("computing", "符号计算 推理", min_score=0.0)
    assert hits and hits[0].content == "符号计算在推理中很关键"
    none = store.search("computing", "符号计算 推理", min_score=100.0)
    assert none == []
    assert build_memory_context([]) == ""
    assert build_memory_context(none) == ""


def test_search_candidate_limit_bounds_scan(tmp_path: Path):
    from datetime import datetime, timedelta, timezone
    store = MemoryStore(tmp_path / "mem.db")
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    store.add(MemoryEntry(agent_id="computing", content="符号计算在推理中很关键", tags=["推理"], updated_at=base))
    store.add(MemoryEntry(agent_id="computing", content="今天吃了苹果", tags=["饮食"], updated_at=base + timedelta(seconds=1)))
    hits = store.search("computing", "符号计算 推理")
    assert hits and hits[0].content == "符号计算在推理中很关键"
    assert store.search("computing", "符号计算 推理", candidate_limit=1) == []
