"""V2 collaboration engine: per-agent persistent memory (T8).

Provides the cross-run memory partition for mode-B collaborators. The design
follows the M2 roundtable resolution: a *minimal* memory slice that

  - partitions entries per agent (persona_id) in a single SQLite store,
  - injects via Top-K keyword retrieval (reusing rag.config.tokenize, which is
    the project's tokenizer - do NOT hand-roll another one),
  - keeps source/links so entries are traceable back to the audit single source
    of truth (do NOT create a second fact orphanage),
  - carries a provenance field that kind=fact entries MUST populate (the
    independently-checkable audit snapshot id), and
  - marks entries stale instead of silently overwriting (FR9 subset).

Write timing rule (roundtable resolution): memory is committed only AFTER a
task's arbitration passes (verdict.ok). See collab.graph._arbitration_node_factory.

This module is intentionally stdlib-only (sqlite3) and imports no heavy deps,
so it can sit next to the collab package without pulling Chroma at import time.
See docs/v2-collaboration-engine-m2-requirements.md section 5.1, 11.2, 12.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tokenize import tokenize
from collab.arbitration import compute_anchor_coverage, detect_decision_conflicts

DEFAULT_TOP_K = 5
DEFAULT_MIN_SCORE = 1.0
DEFAULT_CANDIDATE_LIMIT = 50
_ACTIVE = "active"
_STALE = "stale"
_CORRECTION = "correction"
_DEFAULT_KIND = "judgment"
_OVERRIDDEN = "overridden"
_KINDS = ("fact", "judgment", "preference", "todo", "correction")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _new_memory_id() -> str:
    return "mem-" + uuid.uuid4().hex[:12]


@dataclass
class MemoryEntry:
    """One unit of an agent's cross-run memory.

    Fields:
      id: unique memory id (mem-<hex>).
      agent_id: which persona this memory belongs to (partition key).
      kind: fact | judgment | preference | todo | correction. Default judgment.
      content: the memory body.
      source: provenance string (task id / message id / round number).
      provenance: audit snapshot id; REQUIRED for kind=fact (independently
        checkable), optional otherwise.
      confidence: 0-1 transparent scalar (coverage x recency style).
      status: active | stale | overridden (FR9 governance subset).
      created_at / updated_at: ISO timestamps.
      links: related memory ids (traceability chain).
      tags: retrieval labels (topic / task keywords).
    """

    agent_id: str
    content: str
    id: str = ""
    kind: str = _DEFAULT_KIND
    source: str = ""
    provenance: str = ""
    confidence: float = 0.0
    status: str = _ACTIVE
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    contest_count: int = 0

    def __post_init__(self) -> None:
        # Roundtable resolution: kind=fact must carry an independently checkable
        # provenance (the audit snapshot id), so a self-reinforced "fact" never
        # leaks in without a traceable source. Common-sense guards for the others.
        if self.kind == "fact" and not (self.provenance or "").strip():
            raise ValueError("kind=fact memory requires a provenance (audit snapshot id)")
        if not self.agent_id.strip():
            raise ValueError("memory entry requires a non-empty agent_id")
        if not self.content.strip():
            raise ValueError("memory entry requires non-empty content")
        if self.kind not in _KINDS:
            raise ValueError("unknown memory kind: " + str(self.kind))
        self.confidence = min(1.0, max(0.0, float(self.confidence)))
        if self.contest_count < 0:
            self.contest_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "content": self.content,
            "kind": self.kind,
            "source": self.source,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "status": self.status,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "links": list(self.links),
            "tags": list(self.tags),
            "contest_count": self.contest_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=str(data.get("id") or _new_memory_id()),
            agent_id=str(data.get("agent_id", "")),
            content=str(data.get("content", "")),
            kind=str(data.get("kind", _DEFAULT_KIND)),
            source=str(data.get("source", "")),
            provenance=str(data.get("provenance", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            status=str(data.get("status", _ACTIVE)),
            created_at=_parse_dt(data.get("created_at")) or _now(),
            updated_at=_parse_dt(data.get("updated_at")) or _now(),
            links=[str(x) for x in data.get("links", [])],
            tags=[str(x) for x in data.get("tags", [])],
            contest_count=int(data.get("contest_count", 0) or 0),
        )


def _score(entry: MemoryEntry, query_terms: Counter, *, now: datetime) -> float:
    """Keyword-overlap score + recency/confidence weights (transparent scalar).

    Reuses the project's tokenizer (rag.config.tokenize) and the keyword-overlap
    idea already used by rag.retriever._keyword_score - do NOT reimplement a new
    scoring/semantic engine here. Overlap dominates; recency and confidence only
    weight/sort, never fabricate relevance.
    """
    text = " ".join([entry.content, " ".join(entry.tags), " ".join(entry.links)])
    entry_terms = Counter(tokenize(text))
    if not entry_terms:
        return 0.0
    overlap = float(
        sum(min(count, entry_terms.get(term, 0)) for term, count in query_terms.items())
    )
    if overlap <= 0:
        # No lexical match: a stale/short memory only surfaces when include_stale
        # and top_k is otherwise empty; keep a nominal 0 score.
        return 0.0
    age_days = max(0.0, (now - (entry.updated_at or _now())).total_seconds() / 86400.0)
    recency = 1.0 / (1.0 + age_days / 60.0)
    conf = min(1.5, max(0.5, 1.0 + entry.confidence))
    return overlap * recency * conf


class MemoryStore:
    """SQLite-backed per-agent memory (partition by agent_id).

    Each method opens its own connection (safe across the LangGraph Send
    parallel branches) and re-opens the same PRAGMAs. The store lives at
    db_path, so a fresh store instance on the same path sees prior (cross-run)
    writes.
    """

    def __init__(self, db_path: Path | str, *, parent_dir: Path | str | None = None) -> None:
        self.db_path = Path(db_path)
        if parent_dir is not None:
            Path(parent_dir).mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        """Open a connection that is committed on success and always closed.

        A bare with sqlite3.connect(...) as conn: commits/rolls back the
        transaction but does NOT close the file descriptor - the roundtable
        review found this leaks handles under parallel Send branches. Closing
        here keeps each call self-contained and leaves no open handle behind.
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    provenance TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    links TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    contest_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (agent_id, id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mem_agent_status ON memories(agent_id, status)"
            )

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        """Insert or upsert a memory entry (idempotent by agent_id+id).

        T9 governance: after the write, any EXISTING active entry of the same
        agent that this one explicitly contradicts is demoted to 'overridden'
        and cross-linked. Reuses the M1 decision conflict detector - do NOT
        invent a new one. This is the write-time pollution guard (FR9).
        """
        if not entry.id:
            entry.id = _new_memory_id()
        d = entry.to_dict()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, agent_id, kind, content, source, provenance,
                                      confidence, status, created_at, updated_at, links, tags,
                                      contest_count)
                VALUES (:id, :agent_id, :kind, :content, :source, :provenance,
                        :confidence, :status, :created_at, :updated_at, :links, :tags,
                        :contest_count)
                ON CONFLICT(agent_id, id) DO UPDATE SET
                    content=excluded.content, kind=excluded.kind, source=excluded.source,
                    provenance=excluded.provenance, confidence=excluded.confidence,
                    status=excluded.status, updated_at=excluded.updated_at,
                    links=excluded.links, tags=excluded.tags, contest_count=excluded.contest_count
                """,
                {
                    "id": d["id"],
                    "agent_id": d["agent_id"],
                    "kind": d["kind"],
                    "content": d["content"],
                    "source": d["source"],
                    "provenance": d["provenance"],
                    "confidence": d["confidence"],
                    "status": d["status"],
                    "created_at": d["created_at"],
                    "updated_at": d["updated_at"],
                    "links": json.dumps(d["links"], ensure_ascii=False),
                    "tags": json.dumps(d["tags"], ensure_ascii=False),
                    "contest_count": d["contest_count"],
                },
            )
            conflicts = self._find_conflicts(conn, entry)
            if conflicts:
                # Self-reinforcement guard (roundtable): a NEW entry auto-overrides
                # an older conflicting one ONLY when it is at least as well
                # supported (confidence >=). If any older entry is strictly
                # stronger, the weak NEW entry is itself demoted - a low-confidence
                # new judgment must not erase a well-established memory.
                stronger_old = [
                    row for row in conflicts
                    if float(row["confidence"] or 0.0) > float(entry.confidence or 0.0) + 1e-9
                ]
                if stronger_old:
                    strongest = max(stronger_old, key=lambda r: float(r["confidence"] or 0.0))
                    old_links = json.loads(str(strongest["links"])) if str(strongest["links"]).strip() else []
                    if entry.id not in old_links:
                        old_links.append(entry.id)
                    conn.execute(
                        "UPDATE memories SET links=? WHERE agent_id=? AND id=?",
                        (json.dumps(old_links, ensure_ascii=False), entry.agent_id, str(strongest["id"])),
                    )
                    new_links = list(d["links"])
                    if str(strongest["id"]) not in new_links:
                        new_links.append(str(strongest["id"]))
                    conn.execute(
                        "UPDATE memories SET status=?, links=? WHERE agent_id=? AND id=?",
                        (_OVERRIDDEN, json.dumps(new_links, ensure_ascii=False), entry.agent_id, entry.id),
                    )
                    entry.status = _OVERRIDDEN
                    entry.links = new_links
                else:
                    for row in conflicts:
                        old_id = str(row["id"])
                        old_links = json.loads(str(row["links"])) if str(row["links"]).strip() else []
                        if entry.id not in old_links:
                            old_links.append(entry.id)
                        conn.execute(
                            "UPDATE memories SET status=?, contest_count=?, confidence=?, links=? "
                            "WHERE agent_id=? AND id=?",
                            (
                                _OVERRIDDEN,
                                int(row["contest_count"] or 0) + 1,
                                max(0.0, round(float(row["confidence"] or 0.0) * 0.5, 3)),
                                json.dumps(old_links, ensure_ascii=False),
                                entry.agent_id,
                                old_id,
                            ),
                        )
                    new_links = list(d["links"])
                    for row in conflicts:
                        if str(row["id"]) not in new_links:
                            new_links.append(str(row["id"]))
                    conn.execute(
                        "UPDATE memories SET links=? WHERE agent_id=? AND id=?",
                        (json.dumps(new_links, ensure_ascii=False), entry.agent_id, entry.id),
                    )
                    entry.links = new_links
        return entry

    def _find_conflicts(self, conn: sqlite3.Connection, entry: MemoryEntry) -> list[sqlite3.Row]:
        """Active entries of this agent that this entry explicitly contradicts."""
        rows = conn.execute(
            "SELECT id, links, confidence, contest_count, content FROM memories "
            "WHERE agent_id=? AND status=? AND id!=?",
            (entry.agent_id, _ACTIVE, entry.id),
        ).fetchall()
        return [row for row in rows if detect_decision_conflicts(str(row["content"]), entry.content)]

    def _rows_to_entries(self, rows: list[sqlite3.Row]) -> list[MemoryEntry]:
        entries: list[MemoryEntry] = []
        for row in rows:
            entries.append(
                MemoryEntry(
                    id=str(row["id"]),
                    agent_id=str(row["agent_id"]),
                    kind=str(row["kind"]),
                    content=str(row["content"]),
                    source=str(row["source"]),
                    provenance=str(row["provenance"]),
                    confidence=float(row["confidence"] or 0.0),
                    status=str(row["status"]),
                    created_at=_parse_dt(row["created_at"]) or _now(),
                    updated_at=_parse_dt(row["updated_at"]) or _now(),
                    links=json.loads(str(row["links"])) if str(row["links"]).strip() else [],
                    tags=json.loads(str(row["tags"])) if str(row["tags"]).strip() else [],
                    contest_count=int(row["contest_count"] or 0),
                )
            )
        return entries

    def get(self, agent_id: str, entry_id: str) -> MemoryEntry | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE agent_id=? AND id=?",
                (agent_id, entry_id),
            ).fetchone()
        return self._rows_to_entries([row])[0] if row else None

    def list(self, agent_id: str, *, include_stale: bool = False, limit: int | None = None) -> list[MemoryEntry]:
        if include_stale:
            # include_stale re-includes only STALE entries; overridden entries are
            # ALWAYS excluded (they were superseded, not merely expired).
            sql = "SELECT * FROM memories WHERE agent_id=? AND status!=? ORDER BY updated_at DESC"
            params: list[Any] = [agent_id, _OVERRIDDEN]
        else:
            sql = "SELECT * FROM memories WHERE agent_id=? AND status NOT IN (?, ?) ORDER BY updated_at DESC"
            params = [agent_id, _STALE, _OVERRIDDEN]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._query(sql, params)
        return self._rows_to_entries(rows)

    def search(
        self,
        agent_id: str,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        min_score: float = DEFAULT_MIN_SCORE,
        candidate_limit: int | None = DEFAULT_CANDIDATE_LIMIT,
        include_stale: bool = False,
    ) -> list[MemoryEntry]:
        """Top-K keyword retrieval (reuses rag.config.tokenize for scoring).

        T21 (FR-GAP-2): min_score gates weak lexical hits (score < min_score is
        dropped -> no strong hit, no injection), and candidate_limit bounds how
        many (most-recent) entries are fetched & scored per agent so the scan
        does not grow O(N) with the store. candidate_limit=None -> no cap.
        """
        now = _now()
        query_terms = Counter(tokenize(query))
        candidates = self.list(agent_id, include_stale=include_stale, limit=candidate_limit)
        if not query_terms:
            return candidates[:top_k]
        scored = [(entry, _score(entry, query_terms, now=now)) for entry in candidates]
        hits = [(entry, s) for entry, s in scored if s > 0.0 and s >= min_score]
        # Higher score first; for equal scores, newer first (numeric timestamp).
        hits.sort(key=lambda pair: (-pair[1], -(pair[0].updated_at.timestamp() if pair[0].updated_at else 0.0)))
        return [entry for entry, _ in hits[:top_k]]

    def mark_stale(self, agent_id: str, entry_id: str) -> None:
        # Roundtable: stale must not refresh updated_at (that would inflate its
        # recency and let a recently-expired entry float back to the top).
        with self._conn() as conn:
            conn.execute(
                "UPDATE memories SET status=? WHERE agent_id=? AND id=?",
                (_STALE, agent_id, entry_id),
            )

    def forget(self, agent_id: str, entry_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM memories WHERE agent_id=? AND id=?", (agent_id, entry_id))

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(sql, params).fetchall()

def build_memory_context(entries: list[MemoryEntry], *, max_entries: int = DEFAULT_TOP_K) -> str:
    """Format retrieved memory entries into an injectable prompt segment.

    Marks the memory block boundary so the agent does not mistake a memory for a
    task instruction, and tags fact vs judgment explicitly.
    """
    if not entries:
        return ""
    lines = ["（记忆）以下是与你当前任务相关的过往记忆（非任务指令，仅供背景）："]
    for index, entry in enumerate(entries[:max_entries], start=1):
        kind_label = "已核验事实" if entry.kind == "fact" else "既往判断"
        bits = [f"[{index}]", f"({kind_label})", entry.content.strip()]
        if entry.source:
            bits.append("来源:" + entry.source)
        if entry.provenance:
            bits.append("锚点:" + entry.provenance)
        if entry.status == _STALE:
            bits.append("(已过期)")
        lines.append(" ".join(bits))
    lines.append("（记忆结束）")
    return "\n".join(lines)


def _memory_confidence(audit_summary: str, snapshot_ids: list[str]) -> float:
    """Transparent confidence = anchor coverage of the audit summary.

    Reuses collab.arbitration.compute_anchor_coverage (clamped [0,1]); recency
    is NOT folded in here - it is a retrieval-time signal in _score. 1.0 when
    there are no decisions (no independent evidence required).
    """
    if not audit_summary:
        return 0.0
    try:
        coverage = compute_anchor_coverage(audit_summary, list(snapshot_ids))
        if coverage.decision_count <= 0:
            # No decision points: nothing to verify. Do NOT adopt
            # compute_anchor_coverage's 1.0 (that would be emptiness => certainty)
            # - use a NEUTRAL 0.5 instead (roundtable: vacuous summary is not full
            # confidence).
            return 0.5
        return round(min(1.0, max(0.0, coverage.coverage)), 3)
    except Exception:
        return 0.0


def memory_entries_from_output(task: Any, audit: Any, *, snapshot_ids: list[str] | None = None) -> list[MemoryEntry]:
    """Extract minimal judgment memory entries from an (already passed) audit.

    Deliberately does NOT run an LLM curation pass (roundtable resolution): it
    reads the *structured* output_summary fields. For a passed task we record a
    judgment entry per decision point, plus a shorthand of the task conclusion.
    kind=fact entries are NOT produced here (they require an independently
    checkable provenance, which the executor does not emit) - they are a later
    slice.
    """
    entries: list[MemoryEntry] = []
    if audit is None:
        return entries
    summary = (getattr(audit, "output_summary", "") or "")
    agent_id = str(getattr(task, "persona_id", ""))
    if not agent_id:
        return entries
    source = str(getattr(task, "id", ""))
    # provenance should be an INDEPENDENTLY checkable audit snapshot anchor (the
    # first 24 chars of the task input snapshot, matching the arbitration
    # snapshot-id convention), not just the task id. Fall back to task id when
    # the audit carries no input snapshot.
    provenance = str(getattr(audit, "input_snapshot", "") or "")[:24] or source
    confidence = _memory_confidence(summary, list(snapshot_ids or []))
    for decision in _extract_decision_points(summary):
        entries.append(
            MemoryEntry(
                agent_id=agent_id,
                content="决策点: " + decision,
                kind="judgment",
                source=source,
                provenance=provenance,
                confidence=confidence,
                tags=["decision", agent_id],
            )
        )
    conclusion = _extract_conclusion(summary)
    if conclusion:
        entries.append(
            MemoryEntry(
                agent_id=agent_id,
                content="结论: " + conclusion,
                kind="judgment",
                source=source,
                provenance=provenance,
                confidence=confidence,
                tags=["conclusion", agent_id],
            )
        )
    return entries


def _extract_decision_points(summary: str) -> list[str]:
    out: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("- 关键决策点") or stripped.startswith("关键决策点"):
            body = stripped.split(":", 1)[-1].strip()
            # Accept ASCII/full-width separators and a few numbering styles.
            parts = [p for p in re.split(r"[0-9]+\s*[)）.]", body) if p.strip()]
            for part in parts:
                part = part.strip().strip(";；").strip()
                if part and part not in ("N/A", "无"):
                    out.append(part)
    return out


def _extract_conclusion(summary: str) -> str:
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("- 任务结论") or stripped.startswith("任务结论:"):
            body = stripped.split(":", 1)[-1].strip()
            if body and body not in ("N/A", "无"):
                return body
    return ""


__all__ = [
    "DEFAULT_TOP_K",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_CANDIDATE_LIMIT",
    "MemoryEntry",
    "MemoryStore",
    "build_memory_context",
    "memory_entries_from_output",
]
