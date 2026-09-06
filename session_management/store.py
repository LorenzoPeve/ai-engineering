"""Storage boundary: one Protocol, two backends.

`Session` only ever talks to this interface, so swapping SQLite for flat
files (or Postgres later) touches nothing above this line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from events import Event, SessionMeta


class Store(Protocol):
    """Everything a harness needs from persistence. Note what is missing:
    there is no `update_event` and no `delete_event`. The log is append-only."""

    def create_session(self, meta: SessionMeta) -> SessionMeta: ...

    def get_session(self, session_id: str) -> SessionMeta | None: ...

    def list_sessions(self, limit: int = 20) -> list[SessionMeta]: ...

    def touch_session(self, session_id: str, title: str | None = None) -> None: ...

    def append(self, event: Event) -> Event: ...

    def events(self, session_id: str) -> list[Event]: ...


class JSONLStore:
    """One directory per session: `meta.json` + an append-only `events.jsonl`.

    No dependencies, and every turn shows up as one added line in `git diff`
    — which makes it the better backend for actually watching a harness work.
    """

    def __init__(self, root: str | Path = "./sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, session_id: str) -> Path:
        return self.root / session_id

    def create_session(self, meta: SessionMeta) -> SessionMeta:
        d = self._dir(meta.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps(meta.__dict__, indent=2), "utf-8")
        (d / "events.jsonl").touch()
        return meta

    def get_session(self, session_id: str) -> SessionMeta | None:
        path = self._dir(session_id) / "meta.json"
        if not path.exists():
            return None
        return SessionMeta(**json.loads(path.read_text("utf-8")))

    def list_sessions(self, limit: int = 20) -> list[SessionMeta]:
        metas = [
            SessionMeta(**json.loads((d / "meta.json").read_text("utf-8")))
            for d in self.root.iterdir()
            if (d / "meta.json").exists()
        ]
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas[:limit]

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        from events import utcnow

        meta = self.get_session(session_id)
        if meta is None:
            return
        meta.updated_at = utcnow()
        if title and not meta.title:
            meta.title = title
        (self._dir(session_id) / "meta.json").write_text(
            json.dumps(meta.__dict__, indent=2), "utf-8"
        )

    def append(self, event: Event) -> Event:
        path = self._dir(event.session_id) / "events.jsonl"
        # Line count is the sequence number: position in the file IS the order.
        with path.open("a+", encoding="utf-8") as f:
            f.seek(0)
            event.seq = sum(1 for _ in f) + 1
            f.write(json.dumps(event.__dict__) + "\n")
        return event

    def events(self, session_id: str) -> list[Event]:
        path = self._dir(session_id) / "events.jsonl"
        if not path.exists():
            return []
        return [
            Event(**json.loads(line))
            for line in path.read_text("utf-8").splitlines()
            if line.strip()
        ]
