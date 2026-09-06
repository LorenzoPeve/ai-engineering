"""The SQLite backend. Same Store interface, two tables."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from events import Event, SessionMeta, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    system      TEXT,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Append-only. AUTOINCREMENT gives every event a global, monotonic order,
-- so replay is `ORDER BY seq` and never depends on timestamp resolution.
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    payload     TEXT NOT NULL  -- JSON
);

CREATE INDEX IF NOT EXISTS events_by_session ON events(session_id, seq);
"""


class SQLiteStore:
    def __init__(self, path: str | Path = "./sessions.db") -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def create_session(self, meta: SessionMeta) -> SessionMeta:
        self.conn.execute(
            "INSERT INTO sessions (id, model, system, title, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (meta.id, meta.model, meta.system, meta.title, meta.created_at, meta.updated_at),
        )
        self.conn.commit()
        return meta

    def get_session(self, session_id: str) -> SessionMeta | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return SessionMeta(**dict(row)) if row else None

    def list_sessions(self, limit: int = 20) -> list[SessionMeta]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [SessionMeta(**dict(r)) for r in rows]

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        # COALESCE keeps the first title we ever set; later turns don't rename.
        self.conn.execute(
            "UPDATE sessions SET updated_at = ?, title = COALESCE(title, ?) WHERE id = ?",
            (utcnow(), title, session_id),
        )
        self.conn.commit()

    def append(self, event: Event) -> Event:
        cur = self.conn.execute(
            "INSERT INTO events (session_id, ts, type, payload) VALUES (?, ?, ?, ?)",
            (event.session_id, event.ts, event.type, json.dumps(event.payload)),
        )
        self.conn.commit()
        event.seq = cur.lastrowid
        return event

    def events(self, session_id: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY seq", (session_id,)
        ).fetchall()
        return [
            Event(
                session_id=r["session_id"],
                type=r["type"],
                payload=json.loads(r["payload"]),
                ts=r["ts"],
                seq=r["seq"],
            )
            for r in rows
        ]
