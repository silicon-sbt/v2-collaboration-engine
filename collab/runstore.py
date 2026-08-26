"""V2 collaboration engine: persisted run store (T16, minimal).

M1 kept collaboration runs in memory (_RUNS); M2 persists the run *summary*
(not the full state - roundtable resolution) so run history survives a restart
and get_collab_status / list_collab_runs can query past runs.

The store is deliberately minimal: it holds run metadata + a compact JSON
summary (task_count, per-task statuses, token/cost totals, final_report) rather
than the whole graph state. Uses stdlib sqlite3 with a committed-and-closed
connection per call (same pattern as collab.memory), so it is safe across the
orchestrator's concurrent branches and re-openable cross-instance.

See docs/v2-collaboration-engine-m2-requirements.md section 5.1.4 / 11.2-3.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_CRASH_GRACE_SECONDS = 120


class RunStore:
    """SQLite-backed run-history store (persists the summary, not full state)."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
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
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    stop_reason TEXT,
                    last_heartbeat TEXT,
                    provider TEXT NOT NULL DEFAULT '',
                    mock INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
            # T22 migration: add heartbeat column to stores created before it existed.
            cols = [row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()]
            if "last_heartbeat" not in cols:
                conn.execute("ALTER TABLE runs ADD COLUMN last_heartbeat TEXT")

    def save(self, record: dict[str, Any]) -> None:
        """Upsert a run record (summary is stored as JSON).

        run_id / created_at / provider / mock are creation fields and are left
        immutable on upsert (only status / finished_at / stop_reason / summary
        are refreshed on completion).
        """
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (run_id, status, created_at, finished_at, stop_reason, provider, mock, last_heartbeat, summary)
                VALUES (:run_id, :status, :created_at, :finished_at, :stop_reason, :provider, :mock, :last_heartbeat, :summary)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status, finished_at=excluded.finished_at,
                    stop_reason=excluded.stop_reason, summary=excluded.summary
                """,
                {
                    "run_id": str(record.get("run_id", "")),
                    "status": str(record.get("status", "running")),
                    "created_at": str(record.get("created_at", "")),
                    "finished_at": record.get("finished_at"),
                    "stop_reason": record.get("stop_reason"),
                    "last_heartbeat": record.get("last_heartbeat"),
                    "provider": str(record.get("provider", "")),
                    "mock": 1 if record.get("mock") else 0,
                    "summary": json.dumps(record.get("summary", {}), ensure_ascii=False),
                },
            )

    def touch(self, run_id: str, *, at: datetime | None = None) -> None:
        """Record a heartbeat for a running run (T22 crash recovery)."""
        ts = (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET last_heartbeat=? WHERE run_id=?",
                (ts, str(run_id)),
            )

    def normalize_stale(self, *, crash_grace_seconds: int = DEFAULT_CRASH_GRACE_SECONDS) -> int:
        """Mark still-running runs whose heartbeat expired as failed (T22).

        A run is stale if it is still 'running' and its last heartbeat (or, if
        none was ever recorded, its created_at) is older than crash_grace_seconds.
        It is normalised to status=failed with a crash reason so it never stays
        'running' forever after a crash/restart. Returns the number normalised.
        """
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=crash_grace_seconds)).isoformat(timespec="seconds")
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT run_id FROM runs WHERE status=? AND COALESCE(last_heartbeat, created_at) < ?",
                ("running", cutoff),
            ).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE runs SET status='failed', finished_at=?, stop_reason='crashed (heartbeat expired)' "
                    "WHERE run_id=?",
                    (now.isoformat(timespec="seconds"), str(row["run_id"])),
                )
        return len(rows)

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            summary = json.loads(str(row["summary"]) or "{}")
        except ValueError:
            summary = {}
        return {
            "run_id": str(row["run_id"]),
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "finished_at": row["finished_at"],
            "stop_reason": row["stop_reason"],
            "last_heartbeat": row["last_heartbeat"],
            "provider": str(row["provider"]),
            "mock": bool(row["mock"]),
            "summary": summary,
        }

    def get(self, run_id: str) -> dict[str, Any] | None:
        self.normalize_stale()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def list(self, *, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        self.normalize_stale()
        sql = "SELECT * FROM runs"
        params: tuple[Any, ...] = ()
        if status is not None:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params = params + (int(limit),)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]

__all__ = ["RunStore", "DEFAULT_CRASH_GRACE_SECONDS"]
