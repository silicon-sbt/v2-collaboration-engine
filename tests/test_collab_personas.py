"""Built-in persona library tests (compact cards from agency-agents-zh, MIT)."""

from __future__ import annotations

from collab import persona as persona_module
from collab.persona import get_persona, library_meta, list_personas, persona_hint, render_card


def test_library_is_shipped_and_attributed():
    meta = library_meta()
    cards = list_personas()
    assert len(cards) >= 100
    assert meta.get("license") == "MIT"
    assert "agency-agents-zh" in str(meta.get("source", ""))
    assert get_persona("academic_historian") is not None


def test_persona_hint_renders_a_card_and_stays_compact():
    hint = persona_hint("academic_historian")
    assert "历史学家" in hint
    assert "擅长" in hint
    assert len(hint) < 900, "card hint must stay small: it rides on every task prompt"


def test_persona_hint_falls_back_to_the_bare_id():
    assert persona_hint("a-persona-that-does-not-exist") == "a-persona-that-does-not-exist"
    assert persona_hint("") == ""


def test_list_personas_filters_by_department():
    engineering = list_personas("engineering")
    assert engineering
    assert all(card["department"] == "engineering" for card in engineering)
    assert list_personas("no-such-department") == []


def test_render_card_is_empty_for_an_empty_card():
    assert render_card({}) == ""


def test_missing_library_degrades_to_the_id(monkeypatch, tmp_path):
    monkeypatch.setattr(persona_module, "LIBRARY_PATH", tmp_path / "does-not-exist.json")
    persona_module._payload.cache_clear()
    persona_module._cards.cache_clear()
    try:
        assert persona_hint("academic_historian") == "academic_historian"
        assert list_personas() == []
        assert library_meta() == {}
    finally:
        persona_module._payload.cache_clear()
        persona_module._cards.cache_clear()