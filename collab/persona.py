"""Persona hints for the V2 engine, backed by an optional built-in role library.

A task's persona_id may be a free-form label (the historical behaviour: the id itself is
used as the hint) or the id of a card in the built-in library compiled from
agency-agents-zh (MIT, see NOTICE). Cards are compact on purpose: the hint is injected
into every task prompt, so a card is name / role / worldview / strengths / style
(~240 tokens) instead of the upstream long-form role prompt (~3.4K tokens).

The library is data, not a dependency: if the file is missing the hint degrades to the
bare persona id, which is exactly what this module used to return.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

LIBRARY_PATH = Path(__file__).resolve().parent / "data" / "personas.json"


@lru_cache(maxsize=1)
def _payload() -> dict:
    """Load the compiled library once; any failure means no library."""
    try:
        data = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"_meta": {}, "personas": []}
    if not isinstance(data, dict) or not isinstance(data.get("personas"), list):
        return {"_meta": {}, "personas": []}
    return data


@lru_cache(maxsize=1)
def _cards() -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for card in _payload()["personas"]:
        if isinstance(card, dict) and str(card.get("id", "")).strip():
            cards[str(card["id"])] = card
    return cards


def library_meta() -> dict:
    """Provenance of the built-in library (empty when it is not shipped)."""
    return dict(_payload().get("_meta") or {})


def list_personas(department: str = "") -> list[dict]:
    """Cards in the library, optionally filtered by department."""
    wanted = (department or "").strip().lower()
    cards = list(_cards().values())
    if wanted:
        cards = [c for c in cards if str(c.get("department", "")).lower() == wanted]
    return cards


def get_persona(persona_id: str) -> dict | None:
    """One card by id (None when the id is a free-form label)."""
    return _cards().get(str(persona_id or "").strip())


def render_card(card: dict) -> str:
    """Render a card as the prompt hint. Kept short: it rides on every task prompt."""
    parts: list[str] = []
    name = str(card.get("name") or "").strip()
    role = str(card.get("role") or "").strip()
    if name or role:
        parts.append("名称：" + name + ("（" + role + "）" if role else ""))
    worldview = str(card.get("worldview") or "").strip()
    if worldview:
        parts.append("世界观：" + worldview)
    strengths = [str(s) for s in (card.get("strengths") or []) if str(s).strip()]
    if strengths:
        parts.append("擅长：" + "；".join(strengths))
    style = [str(s) for s in (card.get("style") or []) if str(s).strip()]
    if style:
        parts.append("风格：" + "；".join(style))
    return "\n".join(parts)


def persona_hint(persona_id: str, root_dir=None) -> str:
    """Return the prompt hint for persona_id.

    A card from the built-in library when the id matches one, otherwise the raw id.
    root_dir is accepted for signature parity with the caller and is unused.
    """
    card = get_persona(persona_id)
    if not card:
        return persona_id
    rendered = render_card(card)
    return rendered or persona_id


__all__ = [
    "LIBRARY_PATH",
    "get_persona",
    "library_meta",
    "list_personas",
    "persona_hint",
    "render_card",
]