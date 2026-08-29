"""T17 demo: the zero-config collab demo subcommand (公司模式降门槛入口)."""

from __future__ import annotations

import json
from pathlib import Path

from collab.cli import main
from collab.runstore import RunStore


def _write_tasks(tmp_path: Path) -> Path:
    p = tmp_path / "tasks.json"
    p.write_text(json.dumps([
        {"id": "t1", "persona_id": "computing", "input": "评估符号计算影响", "expected_output": "给方案"},
        {"id": "t2", "persona_id": "history", "input": "评计算工具演变", "expected_output": "给结论"},
    ], ensure_ascii=False), encoding="utf-8")
    return p


def test_cli_demo_runs_mock_scenario(tmp_path: Path, capsys):
    db = tmp_path / "demo_runs.db"
    code = main(["demo", "--mock", "--db", str(db), "--timeout", "60"])
    assert code == 0
    out = capsys.readouterr().out
    assert "collab" in out
    assert "final_report" in out
    store = RunStore(db)
    runs = store.list()
    assert runs and runs[0]["status"] == "done"


def test_cli_demo_uses_custom_tasks(tmp_path: Path, capsys):
    tasks = _write_tasks(tmp_path)
    db = tmp_path / "demo_runs2.db"
    code = main(["demo", "--mock", "--tasks", str(tasks), "--db", str(db), "--timeout", "60"])
    assert code == 0
    store = RunStore(db)
    runs = store.list()
    assert runs and runs[0]["status"] == "done"
