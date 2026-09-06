"""The harness itself: log -> project -> call -> log.

This is ~40 lines of real logic. That is the point — a harness is not a big
idea, it is the small amount of code that turns a stateless endpoint into
something that remembers.
"""

from __future__ import annotations

from events import Event, SessionMeta, new_id, text_of, to_messages
from llm import LLM
from store import Store


class Session:
    def __init__(
        self, store: Store, llm: LLM, meta: SessionMeta, remember: bool = True
    ) -> None:
        self.store = store
        self.llm = llm
        self.meta = meta
        # remember=False keeps logging every turn but sends ONLY the current
        # user message. The endpoint is stateless; the harness is what makes it
        # feel otherwise. Turn the harness off and the amnesia comes right back.
        self.remember = remember

    @classmethod
    def start(
        cls,
        store: Store,
        llm: LLM,
        system: str | None = None,
        remember: bool = True,
    ) -> "Session":
        meta = store.create_session(
            SessionMeta(id=new_id("sess"), model=llm.model, system=system)
        )
        return cls(store, llm, meta, remember=remember)

    @classmethod
    def resume(
        cls, store: Store, llm: LLM, session_id: str, remember: bool = True
    ) -> "Session":
        """Pick a conversation back up. The only state that travels between
        processes is the session id — everything else is rebuilt from the log."""
        meta = store.get_session(session_id)
        if meta is None:
            raise KeyError(f"no such session: {session_id}")
        llm.model = meta.model  # replay on the model that produced the history
        return cls(store, llm, meta, remember=remember)

    def messages(self) -> list[dict]:
        """Rebuilt from the store on every turn, never cached in memory.
        The log is the single source of truth; RAM is just a view of it."""
        return to_messages(self.store.events(self.meta.id))

    def prompt_messages(self) -> list[dict]:
        """What actually goes on the wire. With memory on, the whole log; with
        memory off, just the last user turn."""
        messages = self.messages()
        return messages if self.remember else messages[-1:]

    def send(self, user_text: str) -> str:
        sid = self.meta.id

        # 1. Log the user turn BEFORE calling out, so a crash mid-request
        #    loses the reply, not the question.
        self.store.append(Event(sid, "user_message", {"content": user_text}))

        # 2. Project the log into the wire format and make the call.
        response = self.llm.complete(self.prompt_messages(), system=self.meta.system)

        # 3. Log the assistant turn as full content blocks, plus the metadata
        #    the API will never accept back but you very much want to keep.
        blocks = [b.model_dump(exclude_none=True) for b in response.content]
        self.store.append(
            Event(
                sid,
                "assistant_message",
                {
                    "content": blocks,
                    "model": response.model,
                    "stop_reason": response.stop_reason,
                },
            )
        )
        self.store.append(
            Event(
                sid,
                "usage",
                {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "cache_read_input_tokens": getattr(
                        response.usage, "cache_read_input_tokens", None
                    ),
                },
            )
        )
        self.store.touch_session(sid, title=user_text[:60])

        return text_of(blocks)
