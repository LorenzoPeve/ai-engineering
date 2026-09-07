"""A REPL over the harness. Run it, quit, resume, keep talking.

    python session_management/chat.py                    # new session (sqlite)
    python session_management/chat.py --list
    python session_management/chat.py --resume sess_ab12cd34ef56
    python session_management/chat.py --backend jsonl
    python session_management/chat.py --backend postgres     # needs DATABASE_URL
    python session_management/chat.py --no-memory            # stateless: no history sent
    python session_management/chat.py --show-payload        # print each request body
"""

from __future__ import annotations

import argparse
from pathlib import Path

from events import text_of
from llm import DEFAULT_MODEL, LLM
from session import Session
from sqlite_store import SQLiteStore
from store import JSONLStore

HERE = Path(__file__).resolve().parent


def build_store(backend: str):
    if backend == "sqlite":
        return SQLiteStore(HERE / "data" / "sessions.db")
    if backend == "postgres":
        from postgres_store import PostgresStore  # imported lazily: needs psycopg

        return PostgresStore()
    return JSONLStore(HERE / "data" / "sessions")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bare-bones session manager.")
    parser.add_argument(
        "--backend", choices=("sqlite", "jsonl", "postgres"), default="sqlite"
    )
    parser.add_argument("--resume", metavar="SESSION_ID")
    parser.add_argument("--list", action="store_true", help="list sessions and exit")
    parser.add_argument("--log", metavar="SESSION_ID", help="dump the event log and exit")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--system", default="You are a concise assistant.")
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="send only the current turn (the raw stateless API, no history)",
    )
    parser.add_argument(
        "--show-payload",
        action="store_true",
        help="print the full request body sent to the API on every turn (stderr)",
    )
    args = parser.parse_args()

    (HERE / "data").mkdir(exist_ok=True)
    store = build_store(args.backend)

    if args.list:
        for meta in store.list_sessions():
            print(f"{meta.id}  {meta.updated_at}  {meta.title or '(untitled)'}")
        return

    if args.log:
        for event in store.events(args.log):
            print(f"[{event.seq:>3}] {event.ts} {event.type:<18} {event.payload}")
        return

    llm = LLM(model=args.model, show_payload=args.show_payload)

    remember = not args.no_memory

    if args.resume:
        session = Session.resume(store, llm, args.resume, remember=remember)
        history = session.messages()
        print(f"Resumed {session.meta.id} ({len(history)} messages replayed)\n")
        for message in history[-4:]:
            who = "you" if message["role"] == "user" else "claude"
            print(f"{who}> {text_of(message['content'])[:200]}")
        print()
    else:
        session = Session.start(store, llm, system=args.system, remember=remember)
        print(f"New session {session.meta.id}")
        print(f"Resume with: --resume {session.meta.id}\n")

    if not remember:
        print(
            "NO MEMORY: every turn is sent alone. The log still records "
            "everything (--log SESSION_ID), the model just never sees it.\n"
        )

    print("Type /exit to quit.\n")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text in ("/exit", "/quit"):
            break
        print(f"\nclaude> {session.send(user_text)}\n")

    print(f"\nSession saved: {session.meta.id}")


if __name__ == "__main__":
    main()
