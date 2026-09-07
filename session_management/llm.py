"""The model boundary. Nothing in here knows what a session is."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import anthropic
from anthropic.types import Message
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Set ANTHROPIC_MODEL in .env to switch models everywhere at once.
FALLBACK_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL") or FALLBACK_MODEL

# Adaptive thinking and `output_config.effort` are current-generation features.
# Haiku 4.5 and older models reject them with a 400, so the request has to be
# shaped per model — a real thing any harness has to carry.
_ADAPTIVE_FAMILIES = (
    "claude-opus-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-fable-",
    "claude-mythos-",
)


def supports_adaptive_thinking(model: str) -> bool:
    return model.startswith(_ADAPTIVE_FAMILIES)


@dataclass
class LLM:
    """A thin, stateless wrapper over the Messages API.

    Stateless on purpose: it takes the full `messages` array and returns one
    response. Holding conversation state is the Session's job, not this class's
    — that split is what makes the harness swappable.
    """

    model: str = DEFAULT_MODEL
    max_tokens: int = 16000
    effort: str = "high"  # low | medium | high | xhigh | max (current gen only)
    thinking_budget: int | None = None  # older models only; must be >= 1024
    show_payload: bool = False  # print the request body before every call
    client: anthropic.Anthropic = field(default_factory=anthropic.Anthropic)

    def _request_kwargs(self, messages, system) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        if supports_adaptive_thinking(self.model):
            # The model decides how much to think; `display` keeps a readable
            # trace in the log rather than empty thinking blocks.
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
            kwargs["output_config"] = {"effort": self.effort}
        elif self.thinking_budget:
            # Older models (Haiku 4.5 and back) still take a fixed budget, and
            # error on `effort` entirely — so it is simply never sent.
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(self.thinking_budget, self.max_tokens - 1),
            }
        return kwargs

    def _dump_payload(self, kwargs: dict[str, Any]) -> None:
        """Print the exact request body, so you can watch the messages array
        grow (or not, with --no-memory) turn by turn. stderr, so piping the
        conversation somewhere still works."""
        body = dict(kwargs, stream=True)  # the SDK adds this; show the truth
        print("--- request ---", file=sys.stderr)
        print(json.dumps(body, indent=2, default=str), file=sys.stderr)
        print(
            f"--- {len(kwargs['messages'])} message(s) on the wire ---\n",
            file=sys.stderr,
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
    ) -> Message:
        """One turn. Streams so long replies can't trip the HTTP timeout."""
        kwargs = self._request_kwargs(messages, system)
        if self.show_payload:
            self._dump_payload(kwargs)
        with self.client.messages.stream(**kwargs) as stream:
            return stream.get_final_message()
