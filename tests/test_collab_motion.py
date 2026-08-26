"""FR11 minimal data-layer tests: motion validation, decision (reject must carry
a reason), same-topic merge, and the in-memory MotionStore.
"""

from __future__ import annotations

import pytest

from collab.motion import CollabMotion, MotionStatus, MotionStore, apply_decision, merge_same_topic


def _motion(**kwargs) -> CollabMotion:
    base = {"task_id": "t-1", "topic": "cross-domain conflict", "rationale": "需要集体评审"}
    base.update(kwargs)
    return CollabMotion(**base)


def test_motion_requires_topic_and_budget_source():
    with pytest.raises(ValueError):
        CollabMotion(task_id="t-1", topic="", rationale="x")
    with pytest.raises(ValueError):
        _motion(budget_source="weird")


def test_apply_decision_approve_sets_committee():
    m = _motion(proposed_participants=["computing"])
    apply_decision(m, decision="approved", decided_by="manager", committee=["computing", "history"])
    assert m.status == MotionStatus.APPROVED
    assert m.decided_by == "manager"
    assert m.committee == ["computing", "history"]


def test_apply_decision_reject_requires_reason():
    m = _motion()
    with pytest.raises(ValueError):
        apply_decision(m, decision="rejected")
    # With a reason it is accepted.
    apply_decision(m, decision="rejected", decided_by="manager", reason="topic outside scope")
    assert m.status == MotionStatus.REJECTED
    assert m.decision_reason == "topic outside scope"


def test_merge_same_topic():
    a = _motion()
    b = _motion(task_id="t-2", proposed_participants=["history"])
    motions = merge_same_topic([a, b], topic_key="topic")
    assert a.status == MotionStatus.PENDING
    assert b.status == MotionStatus.MERGED
    assert "history" in a.proposed_participants  # merged participants union


def test_motion_store_decide_and_merge():
    store = MotionStore()
    m1 = store.add(_motion())
    m2 = store.add(_motion(task_id="t-2"))
    assert {m.id for m in store.list(MotionStatus.PENDING)} == {m1.id, m2.id}
    store.decide(m1.id, decision="rejected", decided_by="manager", reason="no budget")
    assert store.get(m1.id).status == MotionStatus.REJECTED
    store.merge_pending()
    # m2 shares the same topic with m1? m1 is REJECTED now, so m2 stays pending.
    assert store.get(m2.id).status == MotionStatus.PENDING


def test_apply_decision_accepts_approve_alias():
    m = _motion()
    apply_decision(m, decision="approve", decided_by="manager")
    assert m.status == MotionStatus.APPROVED


def test_apply_decision_requires_decided_by():
    m = _motion()
    with pytest.raises(ValueError):
        apply_decision(m, decision="approved")


def test_apply_decision_approve_defaults_committee():
    m = _motion(proposed_participants=["computing"])
    apply_decision(m, decision="approve", decided_by="manager")
    assert m.committee == ["computing"]  # defaulted from the applicant proposal


def test_merge_records_traceability():
    a = _motion()
    b = _motion(task_id="t-2")
    merge_same_topic([a, b], topic_key="topic")
    assert a.outputs.get("merged_from") == [b.id]
    assert b.status == MotionStatus.MERGED
    assert b.decided_by == "manager"


def test_from_dict_roundtrip():
    m = _motion(proposed_participants=["computing"], budget_source="global")
    d = m.to_dict()
    back = CollabMotion.from_dict(d)
    assert back.topic == m.topic
    assert back.budget_source == "global"
    assert back.proposed_participants == ["computing"]
    assert back.status == m.status
