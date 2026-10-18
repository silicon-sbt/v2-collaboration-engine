"""Import compact persona cards from the agency-agents-zh role library.

Source (MIT): https://github.com/jnMetaCode/agency-agents-zh
  - Chinese community edition of https://github.com/msitarzewski/agency-agents
  - Copyright (c) 2025 Michael Sitarzewski (original English version)
  - Copyright (c) 2026 jnMetaCode (Chinese translation and localization)

The upstream roles are long-form prompt personas (median ~5.5K chars, ~3.4K tokens).
Injecting one verbatim into every task would double the per-task cost, so this script
does a DETERMINISTIC (no LLM) extraction into a compact card: name / role / worldview /
strengths / style - measured at ~240 tokens, roughly a 14x reduction.

It never copies the upstream files into this repo; the compiled JSON is the only artifact,
and the source remains the upstream repository. Re-run it to refresh.

Usage:
    python scripts/import_agency_personas.py --agency-root ../agency-agents-zh
    python scripts/import_agency_personas.py --agency-root PATH --departments engineering,company
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEPARTMENTS = [
    "academic", "company", "design", "engineering", "finance", "game-development", "gis",
    "hr", "legal", "marketing", "paid-media", "product", "project-management", "sales",
    "security", "spatial-computing", "specialized", "strategy", "supply-chain", "support",
    "testing",
]

META = {
    "source": "https://github.com/jnMetaCode/agency-agents-zh",
    "upstream": "https://github.com/msitarzewski/agency-agents",
    "license": "MIT",
    "copyright": [
        "Copyright (c) 2025 Michael Sitarzewski (original English version)",
        "Copyright (c) 2026 jnMetaCode (Chinese translation and localization)",
    ],
    "note": "Compact cards extracted deterministically from the upstream Markdown roles; "
            "upstream files are NOT vendored here.",
}


def _est_tokens(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return int(cjk / 1.5 + (len(text) - cjk) / 4)


def _frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return "", text
    return match.group(1), text[len(match.group(0)):]


def _field(frontmatter: str, key: str) -> str:
    match = re.search(r"^" + key + r":\s*(.+)$", frontmatter, re.M)
    return match.group(1).strip().strip('"').strip("'") if match else ""


def parse_role(path: Path, root: Path, *, max_strengths: int, max_style: int) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    frontmatter, body = _frontmatter(text)
    name = _field(frontmatter, "name") or path.stem
    role = _field(frontmatter, "description")

    lines = body.splitlines()
    worldview = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">", "|", "-", "*")):
            continue
        worldview = re.sub(r"\*\*", "", stripped)
        break

    sections: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if line.startswith("## "):
            current = re.sub(r"[^\u4e00-\u9fffA-Za-z]", "", line[3:])
            sections[current] = []
        elif current and re.match(r"^\s*[-*]\s+\S", line):
            sections[current].append(re.sub(r"^\s*[-*]\s+", "", line).strip())

    def pick(keys: tuple[str, ...], limit: int) -> list[str]:
        out: list[str] = []
        for heading, bullets in sections.items():
            if any(key in heading for key in keys):
                out.extend(bullets)
        cleaned = [re.sub(r"\*\*", "", b) for b in out if b]
        return [c[:90] for c in cleaned[:limit]]

    return {
        "id": path.stem.replace("-", "_"),
        "department": path.relative_to(root).parts[0],
        "name": name,
        "role": role[:200],
        "worldview": worldview[:180],
        "strengths": pick(("核心使命", "关键规则"), max_strengths),
        "style": pick(("沟通风格",), max_style),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency-root", required=True, help="checkout of agency-agents-zh")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "collab" / "data" / "personas.json"))
    ap.add_argument("--departments", default="", help="comma separated subset (default: all)")
    ap.add_argument("--max-strengths", type=int, default=3)
    ap.add_argument("--max-style", type=int, default=2)
    args = ap.parse_args()

    root = Path(args.agency_root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit("agency root not found: " + str(root))
    wanted = {d.strip() for d in args.departments.split(",") if d.strip()} or set(DEPARTMENTS)

    files = [p for p in sorted(root.rglob("*.md")) if p.relative_to(root).parts[0] in wanted]
    cards: list[dict] = []
    seen: dict[str, int] = {}
    for path in files:
        try:
            card = parse_role(path, root, max_strengths=args.max_strengths, max_style=args.max_style)
        except Exception as exc:  # keep the import resilient to a malformed role file
            print("skip", path.name, exc)
            continue
        if card["id"] in seen:
            seen[card["id"]] += 1
            card["id"] = card["id"] + "_" + str(seen[card["id"]])
        else:
            seen[card["id"]] = 1
        cards.append(card)

    cards.sort(key=lambda c: (c["department"], c["name"]))
    payload = {"_meta": dict(META, imported_roles=len(cards), departments=sorted({c["department"] for c in cards})),
               "personas": cards}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    tokens = [_est_tokens(json.dumps(c, ensure_ascii=False)) for c in cards]
    tokens.sort()
    print("imported roles:", len(cards))
    print("departments:", ", ".join(sorted({c["department"] for c in cards})))
    print("card tokens: median %d, max %d" % (tokens[len(tokens) // 2], tokens[-1]))
    print("written:", out, "(%.1f KB)" % (out.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
