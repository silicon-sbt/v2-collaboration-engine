"""Tests for V2 layered arbitration (T5): conflict detection, anchor coverage,
hard-rule checks, manager provisional review, and graph wiring."""

from __future__ import annotations

from pathlib import Path

from collab.arbitration import (
    compute_anchor_coverage,
    detect_decision_conflicts,
    hard_rules_check,
    manager_arbitrate,
)
from collab.graph import build_collab_graph
from collab.models import Task, TaskAudit, TaskStatus

ROOT = Path(__file__).resolve().parent.parent


def _task(task_id: str, **kwargs) -> Task:
    return Task(id=task_id, persona_id="computing", input="任务", **kwargs)


def _audit(summary: str, reasoning: str = "推理文本", tokens: int = 5) -> TaskAudit:
    return TaskAudit(
        input_snapshot="in",
        output_summary=summary,
        output_reasoning=reasoning,
        token_usage=tokens,
    )


def test_detect_decision_conflicts_same_object_both_verbs():
    conflicts = detect_decision_conflicts("采用方案A；放弃方案A")
    assert conflicts, "expected a conflict"


def test_detect_decision_conflicts_no_false_positive():
    assert detect_decision_conflicts("采用方案A；考虑方案B") == []


def test_anchor_coverage_full_when_no_decisions():
    cov = compute_anchor_coverage("- 关键决策点: N/A", ["s1"])
    assert cov.coverage == 1.0


def test_anchor_coverage_low_without_anchors():
    summary = "- 关键决策点: 1) 判断A; 2) 判断B"
    cov = compute_anchor_coverage(summary, [])
    assert cov.decision_count == 2
    assert cov.coverage == 0.0


def test_anchor_coverage_partial():
    summary = "- 关键决策点: 1) 判断A; 2) 判断B"
    cov = compute_anchor_coverage(summary, ["s1"])
    assert cov.coverage == 0.5


def test_hard_rules_rejects_conflict():
    task = _task("t1")
    audit = _audit("采用方案A；放弃方案A", reasoning="采用方案A 放弃方案A")
    verdict = hard_rules_check(task, audit)
    assert not verdict.ok
    assert verdict.conflicts


def test_hard_rules_ok_clean_audit():
    task = _task("t1")
    audit = _audit("- 引用输入快照: s1\n- 关键决策点: 1) 判断A\n- 任务结论: X")
    verdict = hard_rules_check(task, audit)
    assert verdict.ok


class _ReviseLlm:
    provider_name = "revise"
    model = "revise"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        return "REVISE" + chr(10) + "产出与预期不符"


class _PassLlm:
    provider_name = "pass"
    model = "pass"
    last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def generate(self, prompt: str) -> str:
        return "PASS" + chr(10) + "产出符合预期"


def test_manager_arbitrate_revise():
    task = _task("t1", expected_output="要给出量化结论")
    verdict, reason = manager_arbitrate(_ReviseLlm(), task, _audit("摘要"))
    assert verdict == "revise"
    assert reason


def test_manager_arbitrate_pass():
    task = _task("t1", expected_output="要给出量化结论")
    verdict, _ = manager_arbitrate(_PassLlm(), task, _audit("摘要"))
    assert verdict == "pass"


def test_manager_arbitrate_skip_without_expected():
    task = _task("t1")
    verdict, _ = manager_arbitrate(_ReviseLlm(), task, _audit("摘要"))
    assert verdict == "pass"


def test_graph_arbitration_marks_revise_as_failed():
    tasks = [_task("t1", expected_output="要给出量化结论")]
    app = build_collab_graph(_ReviseLlm(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.FAILED.value, result
    assert result.get("verdict", {}).get("manager") == "revise"
    assert "经理裁决" in result.get("error", ""), result


def test_graph_arbitration_pass_keeps_done():
    tasks = [_task("t1", expected_output="要给出量化结论")]
    app = build_collab_graph(_PassLlm(), root_dir=ROOT)
    state = app.invoke({
        "tasks": [t.to_dict() for t in tasks],
        "results": [],
        "messages": [],
        "token_total": 0,
        "errors": [],
    })
    result = next(r for r in state["results"] if r["id"] == "t1")
    assert result["status"] == TaskStatus.DONE.value
    assert result.get("verdict", {}).get("ok") is True

def test_manager_arbitrate_parse_first_line_exact():
    """Review: a REVISE verdict whose reason mentions PASS must stay REVISE."""

    class _TrickyLlm:
        provider_name = "tricky"
        model = "tricky"
        last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        def generate(self, prompt: str) -> str:
            return "REVISE" + chr(10) + "must PASS quality checks first"

    task = _task("t1", expected_output="要给出量化结论")
    verdict, _ = manager_arbitrate(_TrickyLlm(), task, _audit("摘要"))
    assert verdict == "revise", verdict
