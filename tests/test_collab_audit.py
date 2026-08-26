"""Tests for V2 L2 audit (T2): hard-rule validation and token-usage capture."""

from __future__ import annotations

from unittest import mock

import pytest

from collab.audit import (
    SUMMARY_REQUIRED_FIELDS,
    AuditValidationResult,
    build_audit,
    render_summary_template,
    validate_audit,
)
from collab.models import TaskAudit
from collab.llm import OpenAICompatLLM


def _valid_audit(**overrides) -> TaskAudit:
    summary = render_summary_template(
        snapshot_ids=["snap-001"],
        decisions=["判断A"],
        conclusion="结论B",
    )
    defaults = dict(input_snapshot="in", output_summary=summary, output_reasoning="推理过程：先拆假设，再给判断。", token_usage=42)
    defaults.update(overrides)
    return TaskAudit(**defaults)


def test_render_summary_template_has_required_fields():
    summary = render_summary_template(
        snapshot_ids=["s1", "s2"], decisions=["a", "b"], conclusion="c",
    )
    for field_name in SUMMARY_REQUIRED_FIELDS:
        assert field_name in summary
    assert "s1、s2" in summary
    assert "1) a" in summary


def test_render_summary_template_empty_uses_na():
    summary = render_summary_template()
    assert "N/A" in summary
    for field_name in SUMMARY_REQUIRED_FIELDS:
        assert field_name in summary


def test_validate_audit_ok():
    result = validate_audit(_valid_audit())
    assert result.ok
    assert result.errors == []


def test_validate_audit_none():
    result = validate_audit(None)
    assert not result.ok
    assert "audit is missing" in result.errors


def test_validate_audit_empty_input_snapshot():
    result = validate_audit(_valid_audit(input_snapshot="  "))
    assert not result.ok
    assert any("input_snapshot" in e for e in result.errors)


def test_validate_audit_missing_summary_fields():
    result = validate_audit(_valid_audit(output_summary="只有结论，没有结构化字段"))
    assert not result.ok
    assert any("missing required field" in e for e in result.errors)


def test_validate_audit_negative_tokens():
    # __init__ clamps negative tokens; simulate a corrupted audit via slot write
    audit = _valid_audit()
    audit.token_usage = -1
    result = validate_audit(audit)
    assert not result.ok
    assert any("token_usage" in e for e in result.errors)


def test_validate_audit_skip_summary_fields():
    result = validate_audit(
        _valid_audit(output_summary="自由文本也行"),
        require_summary_fields=False,
    )
    assert result.ok


def test_build_audit_ok():
    audit = build_audit(
        input_snapshot="in",
        output_summary=render_summary_template(conclusion="c"),
        output_reasoning="开放域推理文本",
        token_usage=10,
    )
    assert audit.token_usage == 10
    assert audit.finished_at is not None


def test_build_audit_rejects_invalid():
    with pytest.raises(ValueError, match="audit failed hard-rule checks"):
        build_audit(input_snapshot="", output_summary="bad", token_usage=0)


def test_llm_client_captures_usage():
    llm = OpenAICompatLLM(
        api_key="test", base_url="https://example.com", model="m",
    )
    fake_response = mock.Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    with mock.patch("collab.llm.requests.post", return_value=fake_response):
        text = llm.generate("hello")
    assert text == "hi"
    assert llm.last_usage["total_tokens"] == 15
    assert llm.last_usage["prompt_tokens"] == 10


def test_llm_client_usage_defaults_to_zero_when_absent():
    llm = OpenAICompatLLM(
        api_key="test", base_url="https://example.com", model="m",
    )
    fake_response = mock.Mock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "choices": [{"message": {"content": "hi"}}],
    }
    with mock.patch("collab.llm.requests.post", return_value=fake_response):
        llm.generate("hello")
    assert llm.last_usage["total_tokens"] == 0


def test_llm_client_initial_usage_is_zero():
    llm = OpenAICompatLLM(
        api_key="test", base_url="https://example.com", model="m",
    )
    assert llm.last_usage == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

def test_validate_audit_requires_open_domain_track():
    """Roundtable T3 review: open-domain reasoning must be present (anti-template)."""
    result = validate_audit(_valid_audit(output_reasoning="  "))
    assert not result.ok
    assert any("output_reasoning" in e for e in result.errors)


def test_validate_audit_dual_track_both_present_ok():
    audit = _valid_audit()
    assert audit.output_reasoning.strip()
    assert render_summary_template(conclusion="x")
    assert validate_audit(audit).ok
