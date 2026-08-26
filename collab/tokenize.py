"""Self-contained tokenizer for the V2 engine (no upstream/rag dependency).

Splits text into ASCII alphanumeric/underscore runs plus each CJK codepoint,
matching keyword-overlap scoring in collab.memory (a generic, standard split).
"""

from __future__ import annotations

import re

# ASCII word runs and each CJK ideograph as a token.
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    """Split a string into lowercase tokens for keyword-overlap scoring."""
    return _TOKEN_RE.findall(text.lower())


__all__ = ["tokenize"]
