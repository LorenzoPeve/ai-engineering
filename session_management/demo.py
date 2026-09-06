"""A narrated walkthrough of the harness. Run it and watch the log build.

    python session_management/demo.py                    # sqlite, real API
    python session_management/demo.py --offline          # no API key, no cost
    python session_management/demo.py --backend jsonl
    python session_management/demo.py --backend postgres

Every backend prints the same thing. That is the point of the demo.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from events import to_messages
from llm import LLM
from session import Session

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
WIDTH = min(shutil.get_terminal_size((88, 20)).columns, 88)


def banner(n: int, title: str) -> None:
    print(f"\n\033[1m{'─' * WIDTH}\n {n}. {title}\n{'─' * WIDTH}\033[0m")


def clip(value: object, width: int = WIDTH - 2) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= width else text[: width - 1] + "…"


class OfflineLLM:
    """Stands in for the API so you can watch the plumbing without spending
    money. It answers by quoting the history back, which makes it obvious that
    the whole conversation really is being resent every single turn."""

    model = "offline-echo"

    def complete(self, messages, system=None):
        seen = [m["content"] for m in messages if m["role"] == "user"]
        reply = f"(offline) I was sent {len(messages)} messages. Your first was: {seen[0]!r}"
        return SimpleNamespace(
            content=[SimpleNamespace(model_dump=lambda **k: {"type": "text", "text": reply})],
            model=self.model,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=sum(len(str(m)) for m in messages) // 4,
                output_tokens=len(reply) // 4,
                cache_read_input_tokens=0,
            ),
        )


def build_store(backend: str):
    DATA.mkdir(exist_ok=True)
    if backend == "sqlite":
        from sqlite_store import SQLiteStore

        return SQLiteStore(DATA / "demo.db")
    if backend == "postgres":
        from postgres_store import PostgresStore

        return PostgresStore()
    from store import JSONLStore

    return JSONLStore(DATA / "demo-sessions")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("sqlite", "jsonl", "postgres"), default="sqlite")
    parser.add_argument("--offline", action="store_true", help="no API key, no cost")
    args = parser.parse_args()

    store = build_store(args.backend)
    llm = OfflineLLM() if args.offline else LLM()

    # ── 1 ──────────────────────────────────────────────────────────────────
    banner(1, f"Start a session  (backend: {args.backend})")
    session = Session.start(store, llm, system="You are terse. Answer in one short sentence.")
    print("A row in `sessions`. This id is the ONLY thing you need to come back later:\n")
    for key, value in session.meta.__dict__.items():
        print(f"    {key:<12} {clip(value, 60)}")

    # ── 2 ──────────────────────────────────────────────────────────────────
    banner(2, "Two turns")
    for turn in ["My name is Lorenzo and I ride a horse named Dusty.",
                 "What is the capital of France?"]:
        print(f"\n  you>    {turn}")
        print(f"  claude> {clip(session.send(turn))}")

    # ── 3 ──────────────────────────────────────────────────────────────────
    banner(3, "The log: what actually got stored")
    events = store.events(session.meta.id)
    for event in events:
        print(f"  [{event.seq:>2}] {event.type:<18} {clip(event.payload, WIDTH - 26)}")
    print(f"\n  {len(events)} events. Nothing here was ever updated or deleted.")

    # ── 4 ──────────────────────────────────────────────────────────────────
    banner(4, "The projection: what the API actually sees")
    wire = to_messages(events)
    for message in wire:
        print(f"  {message['role']:<10} {clip(message['content'], WIDTH - 13)}")
    print(f"\n  {len(events)} events  ->  {len(wire)} messages.")
    print("  `usage` events are dropped: bookkeeping you keep, the model never sees.")

    usage = [e.payload for e in events if e.type == "usage"]
    if len(usage) >= 2:
        print(f"\n  input_tokens across turns: {' -> '.join(str(u['input_tokens']) for u in usage)}")
        print("  Climbing, because the ENTIRE history is resent every turn. That is")
        print("  the statelessness you are working around — and why caching exists.")

    # ── 5 ──────────────────────────────────────────────────────────────────
    banner(5, "Throw the object away and resume from the id alone")
    session_id = session.meta.id
    del session  # everything in memory is gone
    print(f"  Session object deleted. Rebuilding from {session_id} ...\n")

    resumed = Session.resume(store, llm, session_id)
    print(f"  Replayed {len(resumed.messages())} messages out of storage.")
    question = "What is my horse's name?"
    print(f"\n  you>    {question}")
    print(f"  claude> {clip(resumed.send(question))}")
    print("\n  It remembered — and no conversation state ever lived in a variable")
    print("  that survived. The store is the only source of truth.")

    print(f"\n\033[1mKeep going:\033[0m")
    print(f"    python session_management/chat.py --resume {session_id}")
    print(f"    python session_management/chat.py --log {session_id}")
    if hasattr(store, "close"):
        store.close()


if __name__ == "__main__":
    main()
