"""Best-effort persona hint for the V2 engine, fully self-contained.

The V2 engine no longer imports the upstream roundtable persona loader. To keep
it dependency-free it does not assume any persona config schema; it returns the
persona id as a neutral hint. Extend this module with the V2 project's own
persona/config format when one is introduced.
"""

from __future__ import annotations


def persona_hint(persona_id: str, root_dir=None) -> str:
    """Return a short hint string for a task prompt.

    Accepts ``persona_id`` (and an unused ``root_dir`` for signature parity) so
    the executor's call sites stay stable. Currently returns the persona id.
    """
    return persona_id


__all__ = ["persona_hint"]
