"""T9 governance tests: conflict detection + auto-override, confidence from
coverage, stale-not-refresh-recency, and input hardening (pollution guard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from collab.memory import MemoryEntry, MemoryStore, memory_entries_from_output


class _TaskAudit:
    def __init__(self, summary: str) -> None:
        self.output_summary = summary


class _TaskLite:
    def __init__(self, persona_id: str, task_id: str) -> None:
        self.persona_id = persona_id
        self.id = task_id


def test_conflicting_judgment_demotes_older(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    a = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", kind="judgment"))
    b = store.add(MemoryEntry(agent_id="computing", content="决策点: 放弃方案A", kind="judgment"))
    a_after = store.get("computing", a.id)
    b_after = store.get("computing", b.id)
    # The older, contradicted entry is demoted and cross-linked.
    assert a_after.status == "overridden"
    assert a_after.contest_count == 1
    assert b.id in a_after.links
    assert a.id in b_after.links
    # And it no longer appears in the active list (won't be injected).
    assert a.id not in [e.id for e in store.list("computing")]
    assert a.id not in [e.id for e in store.search("computing", "方案A")]


def test_no_conflict_keeps_both_active(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    a = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", kind="judgment"))
    b = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案B", kind="judgment"))
    assert store.get("computing", a.id).status == "active"
    assert store.get("computing", b.id).status == "active"


def test_confidence_from_coverage():
    task = _TaskLite("computing", "t-1")
    audit = _TaskAudit("- 关键决策点: 1) 采用符号计算; 2) 证明可行\n- 任务结论: 可行")
    no_anchor = memory_entries_from_output(task, audit)
    with_anchor = memory_entries_from_output(task, audit, snapshot_ids=["snap-1", "snap-2"])
    # With no cross-task anchors, coverage is 0 -> confidence 0.
    assert all(e.confidence == 0.0 for e in no_anchor)
    # With 2 anchors over 2 decisions, coverage = 1 -> confidence 1.
    assert all(e.confidence == 1.0 for e in with_anchor)


def test_mark_stale_does_not_refresh_updated_at(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    e = store.add(MemoryEntry(agent_id="computing", content="旧判断"))
    original_updated_at = store.get("computing", e.id).updated_at
    store.mark_stale("computing", e.id)
    assert store.get("computing", e.id).status == "stale"
    assert store.get("computing", e.id).updated_at == original_updated_at


def test_post_init_hardening():
    with pytest.raises(ValueError):
        MemoryEntry(agent_id="computing", content="x", kind="bogus")
    # Confidence is clamped and contest_count cannot be negative.
    e = MemoryEntry(agent_id="computing", content="x", confidence=2.0, contest_count=-3)
    assert e.confidence == 1.0
    assert e.contest_count == 0


def test_empty_agent_id_rejected():
    with pytest.raises(ValueError):
        MemoryEntry(agent_id="", content="x")


def test_confidence_neutral_when_no_decisions():
    # A summary with NO decision points must NOT be full confidence (avoid
    # "emptiness => certainty"); roundtable: neutralize to 0.5.
    task = _TaskLite("computing", "t-1")
    audit = _TaskAudit("- 引用输入快照: N/A\n- 关键决策点: N/A\n- 任务结论: 可行")
    entries = memory_entries_from_output(task, audit)
    assert entries and all(e.confidence == 0.5 for e in entries)


def test_provenance_uses_audit_snapshot_anchor():
    # provenance should be the audit input_snapshot anchor (first 24 chars), not
    # the task id, so it is independently checkable (matches arbitration).
    class _AuditWithSnap:
        output_summary = "- 关键决策点: 1) 采用符号计算\n- 任务结论: 可行"
        input_snapshot = "snap-0123456789abcdefghijklmnopqrstuv"

    class _TaskSnap:
        persona_id = "computing"
        id = "t-1"

    entries = memory_entries_from_output(_TaskSnap(), _AuditWithSnap())
    expected = _AuditWithSnap.input_snapshot[:24]
    assert entries and all(e.provenance == expected for e in entries)


def test_weak_new_does_not_override_strong_old(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    old = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", confidence=0.9))
    new = store.add(MemoryEntry(agent_id="computing", content="决策点: 放弃方案A", confidence=0.1))
    # The strong old memory survives; the weak new one is itself demoted.
    assert store.get("computing", old.id).status == "active"
    assert store.get("computing", new.id).status == "overridden"
    assert old.id in store.get("computing", new.id).links


def test_strong_new_overrides_weak_old(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    old = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", confidence=0.1))
    new = store.add(MemoryEntry(agent_id="computing", content="决策点: 放弃方案A", confidence=0.9))
    assert store.get("computing", old.id).status == "overridden"
    assert store.get("computing", new.id).status == "active"


def test_include_stale_never_returns_overridden(tmp_path: Path):
    store = MemoryStore(tmp_path / "mem.db")
    a = store.add(MemoryEntry(agent_id="computing", content="决策点: 采用方案A", kind="judgment"))
    b = store.add(MemoryEntry(agent_id="computing", content="决策点: 放弃方案A", kind="judgment"))
    assert store.get("computing", a.id).status == "overridden"
    # Even include_stale=True must not resurrect a superseded (overridden) entry.
    ids = [e.id for e in store.list("computing", include_stale=True)]
    assert a.id not in ids
    assert b.id in ids
