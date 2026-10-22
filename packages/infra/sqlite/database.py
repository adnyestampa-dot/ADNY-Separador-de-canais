from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    import os

    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    db_dir = Path(appdata) / "ADNY Separador"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "adny_separador.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT,
    path TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    skill_id TEXT,
    status TEXT,
    params TEXT,
    result TEXT,
    started_at TEXT,
    finished_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS presets_textile (
    id TEXT PRIMARY KEY,
    name TEXT,
    config TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    event_type TEXT,
    payload TEXT,
    timestamp TEXT,
    job_id TEXT
);
"""


class Database:
    """Simple SQLite persistence layer."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or get_db_path()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._path),
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._migrate_jobs_table()
            logger.info("SQLite conectado: %s", self._path)
        return self._conn

    def _migrate_jobs_table(self) -> None:
        conn = self._conn
        if conn is None:
            return
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "error" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN error TEXT")
            conn.commit()

    def log_job(
        self,
        job_id: str,
        skill_id: str,
        status: str,
        params: dict | None = None,
        result: dict | None = None,
        *,
        finished_at: str | None = None,
        error: str | None = None,
    ) -> None:
        conn = self.connect()
        now = datetime.now().isoformat()
        existing = conn.execute("SELECT started_at FROM jobs WHERE id = ?", (job_id,)).fetchone()
        started = existing["started_at"] if existing else now
        conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(id, skill_id, status, params, result, started_at, finished_at, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                skill_id,
                status,
                json.dumps(params or {}, ensure_ascii=False),
                json.dumps(result or {}, ensure_ascii=False),
                started,
                finished_at or (now if status in ("completed", "failed") else None),
                error,
            ),
        )
        conn.commit()

    def record_audit_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        job_id: str | None = None,
    ) -> None:
        conn = self.connect()
        conn.execute(
            "INSERT INTO audit_events (session_id, event_type, payload, timestamp, job_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                datetime.now().isoformat(),
                job_id,
            ),
        )
        conn.commit()

    def get_audit_events(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        conn = self.connect()
        query = "SELECT * FROM audit_events WHERE 1=1"
        params: list[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            out.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "event_type": row["event_type"],
                    "payload": json.loads(row["payload"] or "{}"),
                    "timestamp": row["timestamp"],
                    "job_id": row["job_id"],
                }
            )
        return out

    def get_recent_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self.connect()
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "id": row["id"],
                "skill_id": row["skill_id"],
                "status": row["status"],
                "params": json.loads(row["params"] or "{}"),
                "result": json.loads(row["result"] or "{}"),
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "error": row["error"],
            }
            for row in rows
        ]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
