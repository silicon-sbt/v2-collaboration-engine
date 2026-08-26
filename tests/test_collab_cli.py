"""T17 tests: the collab workflow runner/CLI (company mode entry) + mode threading.
"""

from __future__ import annotations

import json
from pathlib import Path

from collab.cli import main
from collab.runner import get_collab_status, run_collaboration
from collab.runstore import RunStore


def _write_tasks(tmp_path: Path) -> Path:
    p = tmp_path / "tasks.json"
    p.write_text(json.dumps([
        {"id": "t1", "persona_id": "computing", "input": "评估符号计算影响", "expected_output": "给方案"},
        {"id": "t2", "persona_id": "history", "input": "评计算工具演变", "expected_output": "给结论"},
    ], ensure_ascii=False), encoding="utf-8")
    return p


def test_cli_run_wait_persists(tmp_path: Path, capsys):
    tasks = _write_tasks(tmp_path)
    db = tmp_path / "runs.db"
    code = main(["run", str(tasks), "--mock", "--db", str(db)])
    assert code == 0
    store = RunStore(db)
    runs = store.list()
    assert runs, "a run should be persisted"
    run_id = runs[0]["run_id"]
    assert runs[0]["status"] == "done"
    out = capsys.readouterr().out
    assert "run_id:" in out
    assert "done" in out


def test_cli_status_and_list(tmp_path: Path, capsys):
    tasks = _write_tasks(tmp_path)
    db = tmp_path / "runs.db"
    main(["run", str(tasks), "--mock", "--db", str(db)])
    store = RunStore(db)
    run_id = store.list()[0]["run_id"]
    main(["status", run_id, "--db", str(db)])
    out = capsys.readouterr().out
    assert '"status": "done"' in out
    main(["list", "--db", str(db)])
    out2 = capsys.readouterr().out
    assert run_id in out2


def test_cli_status_unknown(tmp_path: Path, capsys):
    db = tmp_path / "runs.db"
    main(["status", "nope", "--db", str(db)])
    out = capsys.readouterr().out
    assert '"not_found"' in out


def test_runner_threads_mode_parallel(tmp_path: Path):
    store = RunStore(tmp_path / "runs.db")
    tasks = [
        {"id": "t1", "persona_id": "computing", "input": "调研A"},
        {"id": "t2", "persona_id": "history", "input": "调研B"},
    ]
    run_id = run_collaboration(tasks, mock=True, mode="parallel", run_store=store)
    for _ in range(50):
        status = get_collab_status(run_id, run_store=store)["status"]
        if status not in ("running",):
            break
        import time
        time.sleep(0.05)
    st = get_collab_status(run_id, run_store=store)
    assert st["status"] == "done"
    assert "模式: parallel（experimental）" in st["final_report"]


def test_build_summary_includes_cost_waste_recovery():
    from collab.runner import _build_summary

    record = {
        "run_id": "r1",
        "status": "done",
        "created_at": "2025-01-01T00:00:00+00:00",
        "finished_at": "2025-01-01T00:00:01+00:00",
        "stop_reason": None,
        "error": None,
        "provider": "openai",
        "mock": False,
        "state": {
            "tasks": [{"id": "t1", "persona_id": "computing", "input": "x"}],
            "results": [
                {
                    "id": "t1",
                    "status": "done",
                    "verdict": {"ok": True},
                    "audit": {
                        "persona_id": "computing",
                        "token_usage": 100,
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "cost_usd": 0.02,
                        "memory_tokens": 200,
                    },
                }
            ],
            "token_total": 100,
            "attempts": [],
            "final_report": "# report",
        },
    }
    s = _build_summary(record)
    assert s["cost_usd"] == 0.02
    assert s["cost_by_persona"]["computing"] == 0.02
    assert s["memory_tokens"] == 200
    # openai input rate 0.00015/1K -> 200*0.00015/1000
    assert abs(s["memory_cost_usd"] - 0.00003) < 1e-9
    assert abs(s["memory_share"] - 0.00003 / 0.02) < 1e-9
    assert "waste_cost_usd" not in s  # no waste => field omitted
    assert s.get("recovery_rate") is None


def test_cli_cost_reads_persisted_summary(tmp_path: Path, capsys):
    db_path = tmp_path / "runs.db"
    store = RunStore(db_path)
    store.save(
        {
            "run_id": "r-cost",
            "status": "done",
            "created_at": "2025-01-01T00:00:00+00:00",
            "finished_at": "2025-01-01T00:00:01+00:00",
            "stop_reason": None,
            "error": None,
            "provider": "openai",
            "mock": False,
            "summary": {
                "run_id": "r-cost",
                "status": "done",
                "cost_usd": 0.02,
                "cost_priced_usd": 0.024,
                "cost_estimated_usd": 0.0,
                "cost_by_persona": {"computing": 0.02},
                "memory_tokens": 200,
                "memory_cost_usd": 0.00003,
                "memory_share": 0.0015,
                "waste_cost_usd": 0.005,
                "waste_tokens": 20,
                "waste_reasons": ["transient retry"],
                "retries_that_succeeded": 1,
                "tasks_that_retried": 1,
                "recovery_rate": 1.0,
            },
        }
    )
    assert main(["cost", "r-cost", "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert abs(data["cost_usd"] - 0.02) < 1e-9
    assert data["memory_tokens"] == 200
    assert abs(data["memory_cost_usd"] - 0.00003) < 1e-9
    assert abs(data["waste_cost_usd"] - 0.005) < 1e-9
    assert data["recovery_rate"] == 1.0

