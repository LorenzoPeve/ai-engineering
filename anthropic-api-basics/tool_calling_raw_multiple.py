"""
Content blocks at the wire level: why `content` is a LIST.

Runs four scenarios against the same tool set. Each one is engineered to make
the model return a different block shape, so you can see the list actually
vary instead of always being [TextBlock].

    1. text_only      -> [text]
    2. narrate_then_call -> [text, tool_use]
    3. parallel_calls -> [text?, tool_use, tool_use, tool_use]
    4. thinking       -> [thinking, text?, tool_use]

Nothing is executed — this is one POST per scenario, no agent loop. The point
is the response shape, not the result.

Run it:
    python content_blocks_raw.py
"""

import json
import os
from collections import Counter
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5"

HEADERS = {
    "x-api-key": os.environ["ANTHROPIC_API_KEY"],
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a single city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Austin'"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    },
    {
        "name": "get_timezone",
        "description": "Get the current local time and UTC offset for a city.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# THE SCENARIOS
#
# Block shape is a BEHAVIOR, not a setting. You can't ask the API for two
# tool_use blocks — you ask a question that needs two lookups and the model
# emits them. Each payload below is a small experiment in eliciting a shape.
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = {
    # No tool applies. The model answers directly. Baseline: one text block,
    # stop_reason "end_turn". Note the tools are still sent and still cost
    # input tokens even when unused.
    "1_text_only": {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": TOOLS,
        "messages": [{"role": "user", "content": "In one sentence, what is a tool schema?"}],
    },

    # A system prompt that demands narration before acting. This is how you
    # reliably get [text, tool_use] — the model says something, THEN calls.
    # Same single stream of tokens; the server slices it into two blocks at
    # the tool-call delimiter.
    "2_narrate_then_call": {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": TOOLS,
        "system": (
            "Before using any tool, briefly tell the user what you are about to "
            "do and why, in one short sentence. Then make the call."
        ),
        "messages": [{"role": "user", "content": "What's the weather in Austin?"}],
    },

    # Three independent lookups, none depending on another's result. The model
    # can request them all in ONE assistant message -> several tool_use blocks.
    # This is the case that breaks any code doing response.content[0].
    #
    # Try flipping disable_parallel_tool_use to True and re-running: same
    # question, but you'll get one call per turn instead. That toggle is the
    # cleanest proof that parallelism is the model's choice, not the API's.
    "3_parallel_calls": {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": TOOLS,
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": False},
        "messages": [{
            "role": "user",
            "content": "Compare the current weather in Austin, Denver, and Miami.",
        }],
    },

    # Extended thinking on. Reasoning tokens arrive as their own block type,
    # ahead of everything else — the model's reasoning is in context when it
    # picks the tool, which is the whole mechanism by which thinking helps.
    # max_tokens must exceed budget_tokens.
    "4_thinking": {
        "model": MODEL,
        "max_tokens": 3000,
        "tools": TOOLS,
        "thinking": {"type": "enabled", "budget_tokens": 2000},
        "messages": [{
            "role": "user",
            "content": (
                "I have a 7am flight out of Denver tomorrow. Is the weather there "
                "likely to be a problem, and what time is it there right now?"
            ),
        }],
    },
}


def describe(content: list) -> str:
    """Render the block shape compactly, e.g. '[text, tool_use x3]'."""
    counts = Counter(b["type"] for b in content)
    return "[" + ", ".join(
        t if n == 1 else f"{t} x{n}" for t, n in counts.items()
    ) + "]"


def run_scenario(name: str, payload: dict) -> dict:
    print(f"\n{'═' * 72}\n  {name}\n{'═' * 72}")

    response = httpx.post(URL, headers=HEADERS, json=payload, timeout=60.0)
    data = response.json()

    if response.status_code != 200:
        print(f"HTTP {response.status_code}")
        print(json.dumps(data, indent=2))
        return {"request": payload, "response": data}

    content = data["content"]
    print(f"stop_reason : {data['stop_reason']}")
    print(f"block count : {len(content)}")
    print(f"shape       : {describe(content)}")

    # Walk the blocks. This is the discriminated-union pattern: branch on
    # `type`, because each block class carries different fields. A ToolUseBlock
    # has no .text; a TextBlock has no .input. There is no safe common accessor.
    for i, block in enumerate(content):
        kind = block["type"]
        print(f"\n  [{i}] type={kind}")

        if kind == "text":
            print(f"      text: {block['text'][:220]}")
        elif kind == "thinking":
            print(f"      thinking ({len(block['thinking'])} chars): "
                  f"{block['thinking'][:220]}...")
        elif kind == "tool_use":
            # `input` is the ONLY part of this whole response the model
            # actually authored as JSON. Everything else — the block wrapper,
            # the id, the type field — was assembled by the server.
            print(f"      id   : {block['id']}")
            print(f"      name : {block['name']}")
            print(f"      input: {json.dumps(block['input'])}")
        else:
            print(f"      {json.dumps(block)[:220]}")

    return {"request": payload, "response": data}


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)

    results = {}
    for name, payload in SCENARIOS.items():
        results[name] = run_scenario(name, payload)

    out_path = out_dir / "content_blocks_raw.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Side-by-side summary — the actual payoff of the script.
    print(f"\n\n{'═' * 72}\n  SUMMARY\n{'═' * 72}")
    print(f"  {'scenario':<22} {'stop_reason':<12} {'blocks':<7} shape")
    print(f"  {'-' * 22} {'-' * 12} {'-' * 7} {'-' * 24}")
    for name, r in results.items():
        resp = r["response"]
        if "content" not in resp:
            print(f"  {name:<22} {'ERROR':<12}")
            continue
        print(f"  {name:<22} {resp['stop_reason']:<12} "
              f"{len(resp['content']):<7} {describe(resp['content'])}")

    print(f"\n--- full request+response saved to {out_path}")

    # ── Things to try ────────────────────────────────────────────────────────
    #
    # 1. Set disable_parallel_tool_use=True in scenario 3. Watch the shape
    #    collapse to a single tool_use. Nothing else changed.
    #
    # 2. Delete the system prompt from scenario 2. The [text, tool_use] shape
    #    usually becomes just [tool_use] — narration was a prompt effect.
    #
    # 3. Add "tool_choice": {"type": "any"} to scenario 1, forcing a call on a
    #    question no tool fits. See what it invents. Good argument for "auto".
    #
    # 4. Take scenario 3's response, append it verbatim as an assistant message
    #    plus one user message containing ALL the tool_results, and POST again.
    #    Omit one result and read the 400 — that error is the clearest possible
    #    explanation of why tool_use_id exists.


if __name__ == "__main__":
    main()