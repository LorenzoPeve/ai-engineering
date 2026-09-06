"""The Postgres backend. Same Store protocol, same two tables.

Why a third backend: SQLite and JSONL are single-writer, single-machine. The
moment two processes (a web worker and a cron job, say) touch the same session,
you want a real database. Nothing above `store.py` changes — that is the whole
argument for having put a Protocol there.

Requires `psycopg[binary]` (psycopg 3):

    pip install "psycopg[binary]"
"""

from __future__ import annotations

import os

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from events import Event, SessionMeta, utcnow

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/harness"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    model       TEXT NOT NULL,
    system      TEXT,
    title       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- BIGSERIAL is the Postgres spelling of SQLite's AUTOINCREMENT. Sequences are
-- transactional and gap-tolerant: `seq` is guaranteed increasing, not dense.
-- Replay only ever cares about ORDER BY, so gaps are fine.
CREATE TABLE IF NOT EXISTS events (
    seq         BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,
    payload     JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS events_by_session ON events(session_id, seq);
"""


class PostgresStore:
    def __init__(self, dsn: str | None = None) -> None:
        self.conn = psycopg.connect(
            dsn or os.environ.get("DATABASE_URL", DEFAULT_DSN),
            row_factory=dict_row,
            autocommit=True,
        )
        self.conn.execute(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def create_session(self, meta: SessionMeta) -> SessionMeta:
        self.conn.execute(
            "INSERT INTO sessions (id, model, system, title, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (meta.id, meta.model, meta.system, meta.title, meta.created_at, meta.updated_at),
        )
        return meta

    def get_session(self, session_id: str) -> SessionMeta | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = %s", (session_id,)
        ).fetchone()
        return SessionMeta(**row) if row else None

    def list_sessions(self, limit: int = 20) -> list[SessionMeta]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT %s", (limit,)
        ).fetchall()
        return [SessionMeta(**r) for r in rows]

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        self.conn.execute(
            "UPDATE sessions SET updated_at = %s, title = COALESCE(title, %s) WHERE id = %s",
            (utcnow(), title, session_id),
        )

    def append(self, event: Event) -> Event:
        # RETURNING is how you get the generated key without a second round-trip.
        row = self.conn.execute(
            "INSERT INTO events (session_id, ts, type, payload)"
            " VALUES (%s, %s, %s, %s) RETURNING seq",
            (event.session_id, event.ts, event.type, Jsonb(event.payload)),
        ).fetchone()
        event.seq = row["seq"]
        return event

    def events(self, session_id: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = %s ORDER BY seq", (session_id,)
        ).fetchall()
        # JSONB comes back already decoded — no json.loads(), unlike SQLite.
        return [
            Event(
                session_id=r["session_id"],
                type=r["type"],
                payload=r["payload"],
                ts=r["ts"],
                seq=r["seq"],
            )
            for r in rows
        ]
