"""T18 tests: memory + motion CLI subcommands (persisted) for the company workflow entry.
"""

from __future__ import annotations

from pathlib import Path

from collab.cli import main
from collab.memory import MemoryEntry, MemoryStore
from collab.motion import CollabMotion, MotionStatus, MotionStore


def _push_memory(db: Path) -> None:
    store = MemoryStore(db)
    store.add(MemoryEntry(agent_id="computing", content="符号计算是关键变量", tags=["推理"]))


def test_cli_memory_search_and_list(tmp_path: Path, capsys):
    db = tmp_path / "mem.db"
    _push_memory(db)
    assert main(["memory", "search", "computing", "符号", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "符号计算是关键变量" in out
    assert main(["memory", "list", "computing", "--db", str(db)]) == 0
    out2 = capsys.readouterr().out
    assert "符号计算是关键变量" in out2


def test_cli_motion_submit_decide_list_persist(tmp_path: Path, capsys):
    db = tmp_path / "motions.db"
    assert main(["motion", "submit", "t-1", "跨域冲突", "需要集体评审", "--participants", '["computing"]', "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert '"task_id": "t-1"' in out
    motion_id = out.split('"id": "')[1].split('"')[0]
    # decide approve (separate process-equivalent = new MotionStore on same db)
    assert main(["motion", "decide", motion_id, "approved", "--committee", '["computing", "history"]', "--db", str(db)]) == 0
    capsys.readouterr()
    assert main(["motion", "list", "--status", "approved", "--db", str(db)]) == 0
    out2 = capsys.readouterr().out
    assert motion_id in out2
    assert '"committee"' in out2


def test_cli_motion_reject_without_reason_errors(tmp_path: Path, capsys):
    db = tmp_path / "motions.db"
    assert main(["motion", "submit", "t-1", "主题", "理由", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    motion_id = out.split('"id": "')[1].split('"')[0]
    code = main(["motion", "decide", motion_id, "rejected", "--db", str(db)])
    assert code == 1
    err = capsys.readouterr().err
    assert "reason" in err


def test_cli_run_writes_memory_then_read(tmp_path: Path, capsys):
    import json
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps([
        {"id": "t1", "persona_id": "computing", "input": "评估符号计算影响", "expected_output": "给方案"}
    ], ensure_ascii=False), encoding="utf-8")
    memdb = tmp_path / "mem.db"
    assert main(["run", str(tasks), "--mock", "--memory-db", str(memdb)]) == 0
    capsys.readouterr()
    assert main(["memory", "list", "computing", "--db", str(memdb)]) == 0
    out = capsys.readouterr().out
    # the run's arbitration-passed output was persisted to the SAME memory store.
    assert "决策点" in out or "结论" in out


def test_motion_store_cross_instance_persist(tmp_path: Path):
    db = tmp_path / "motions.db"
    store1 = MotionStore(db)
    m = store1.add(CollabMotion(task_id="t-1", topic="主题", rationale="理由"))
    store2 = MotionStore(db)
    got = store2.get(m.id)
    assert got is not None
    assert got.topic == "主题"
    assert got.status == MotionStatus.PENDING
