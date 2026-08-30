"""Tests for the V2 report run-path (MOCK / REAL) label."""

from __future__ import annotations

import time

from collab.graph import _build_collab_report
from collab.runner import get_collab_status, run_collaboration


def _wait(run_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = get_collab_status(run_id)
        if s["status"] != "running":
            return s
        time.sleep(0.05)
    return get_collab_status(run_id)


def test_mock_run_report_has_mock_path():
    """A mock run must label its path MOCK in the report (review: 路径标识)."""
    run_id = run_collaboration([{"id": "t1", "persona_id": "computing", "input": "x"}], mock=True)
    st = _wait(run_id)
    assert st["status"] == "done"
    assert "运行路径: MOCK" in st["final_report"]


def test_report_real_label():
    report = _build_collab_report([], {}, token_total=0, attempts=[], run_path="REAL:deepseek")
    assert "运行路径: REAL:deepseek" in report


def test_report_unknown_default():
    report = _build_collab_report([], {}, token_total=0, attempts=[])
    assert "运行路径: UNKNOWN" in report
