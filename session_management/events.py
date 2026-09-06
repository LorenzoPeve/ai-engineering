"""The log. Everything that happens in a session becomes an Event.

The key idea: the event log is a SUPERSET of what the API wants. It holds
usage, errors and notes alongside the messages. `to_messages()` is a pure
projection from the log down to the wire format the Messages API accepts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Event types that project into the API `messages` array. Everything else
# (usage, error, note) is harness bookkeeping the model never sees.
WIRE_EVENTS = ("user_message", "assistant_message")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class SessionMeta:
    """One row of the `sessions` table."""

    id: str
    model: str
    system: str | None = None
    title: str | None = None
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)


@dataclass
class Event:
    """One row of the `events` table. Append-only — never updated in place."""

    session_id: str
    type: str
    payload: dict[str, Any]
    ts: str = field(default_factory=utcnow)
    seq: int | None = None  # assigned by the store on append


def to_messages(events: list[Event]) -> list[dict[str, Any]]:
    """Project the log into the `messages` array for the next API call.

    Assistant turns are replayed as their full content blocks, not as plain
    text: thinking blocks must be echoed back unchanged when you continue on
    the same model, and tool_use blocks have to pair with their tool_result.
    Flattening to a string here would silently drop both.
    """
    messages: list[dict[str, Any]] = []
    for event in events:
        if event.type == "user_message":
            messages.append({"role": "user", "content": event.payload["content"]})
        elif event.type == "assistant_message":
            messages.append({"role": "assistant", "content": event.payload["content"]})
    return messages


def text_of(content: Any) -> str:
    """Pull the readable text out of a content value (str or block list)."""
    if isinstance(content, str):
        return content
    return "".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
