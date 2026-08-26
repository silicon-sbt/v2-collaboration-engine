"""Tests for the workflow feedback-driven modes: light mode (#1),
deliverable-first summary (#2), and audit-model differentiation (#3).
"""

from __future__ import annotations

from pathlib import Path

from collab.cli import main
from collab.graph import build_collab_graph
from collab.models import Task
from collab.runner import get_collab_status, run_collaboration
from collab.runstore import RunStore

ROOT = Path(__file__).resolve().parent.parent


class GoodLlm:
    provider_name = "mock"
    model = "mock"
    last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def generate(self, prompt: str) -> str:
        return "采用了方案A，理由：成本可控。"


class ReviseLlm:
    provider_name = "mock"
    model = "mock"
    last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def generate(self, prompt: str) -> str:
        return "REVISE 不满足任务意图"


class PassLlm:
    provider_name = "mock"
    model = "mock"
    last_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def generate(self, prompt: str) -> str:
        return "PASS 满足任务意图"


def _invoke(llm, *, audit_llm=None, light=False):
    app = build_collab_graph(llm, root_dir=ROOT, audit_llm=audit_llm, light=light)
    task = Task(id="t1", persona_id="computing", input="x", expected_output="y")
    state = app.invoke({"tasks": [task.to_dict()], "results": [], "messages": [], "token_total": 0, "errors": []})
    return next(r for r in state["results"] if r["id"] == "t1")


def test_light_mode_skips_manager_arbitration():
    res = _invoke(ReviseLlm(), light=True)
    assert res["status"] == "done"
    assert res["verdict"]["ok"] is True
    res2 = _invoke(ReviseLlm())
    assert res2["status"] == "failed"
    assert res2["verdict"]["failure_type"] == "manager_revise"


def test_audit_model_differentiates_arbitration():
    res_revise = _invoke(GoodLlm(), audit_llm=ReviseLlm())
    assert res_revise["status"] == "failed"
    assert res_revise["verdict"]["failure_type"] == "manager_revise"
    res_pass = _invoke(GoodLlm(), audit_llm=PassLlm())
    assert res_pass["status"] == "done"
    assert res_pass["verdict"]["ok"] is True


def test_cli_report_summary_is_deliverable_first(tmp_path: Path, capsys):
    store = RunStore(tmp_path / "runs.db")
    run_id = run_collaboration(
        [{"id": "t1", "persona_id": "computing", "input": "x"}], mock=True, run_store=store
    )
    for _ in range(50):
        status = get_collab_status(run_id, run_store=store)["status"]
        if status != "running":
            break
        import time; time.sleep(0.05)
    assert main(["report", run_id, "--summary", "--db", str(store.db_path)]) == 0
    out = capsys.readouterr().out
    assert "# 交付物摘要" in out
    assert "## 任务结果" in out
    assert "损耗(USD)" not in out
    assert "成本(USD)" not in out
