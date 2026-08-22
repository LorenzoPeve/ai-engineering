"""
Tool calling from scratch — no framework, no abstractions.

Setup:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    python tool_calling_mre.py

The point of this file is the printed message array. Watch it grow.
Everything you'll later call an "agent" is this loop plus better plumbing.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

MODEL = "claude-haiku-4-5"
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

TOOL_SCHEMAS = [
    {
        "name": "calculate",
        "description": (
            "Evaluate an arithmetic expression and return the numeric result. "
            "Use this for any calculation rather than computing it yourself, "
            "so the answer is exact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "A Python arithmetic expression, e.g. '847 * 23' or '(15000 / 12) ** 0.5'",
                }
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_current_time",
        "description": (
            "Get the current UTC date and time. Use this whenever the user's "
            "question depends on what today's date is."
        ),
        "input_schema": {
            # No parameters. Still needs a valid schema — an empty object.
            "type": "object",
            "properties": {},
        },
    },
]


def calculate(expression: str) -> str:
    # eval() is a terrible idea outside a toy. Sandbox this in anything real —
    # tool inputs are model-generated, which means they are untrusted input.
    return str(eval(expression, {"__builtins__": {}}, {}))


def get_current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


TOOL_FUNCTIONS = {
    "calculate": calculate,
    "get_current_time": get_current_time,
}


def run_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool. Returns (result_text, is_error).

    Note what happens on failure: we do NOT raise. We catch the exception and
    hand the error text back to the model as the tool result. The model will
    read it and usually correct itself — a malformed expression gets retried
    with valid syntax. Errors are conversation, not crashes. This single habit
    is most of what makes an agent feel robust.
    """
    try:
        fn = TOOL_FUNCTIONS[name]
        return str(fn(**tool_input)), False
    except Exception as e:
        return f"{type(e).__name__}: {e}", True


# Everything printed also lands here, so the run can be read back later.
# The terminal gets a truncated view; the file gets the whole thing.
LOG_LINES: list[str] = []


def log(text: str = "") -> None:
    print(text)
    LOG_LINES.append(text)


def dump(label: str, obj) -> None:
    log(f"\n{'─' * 70}\n{label}\n{'─' * 70}")
    pretty = json.dumps(obj, indent=2, default=str)
    print(pretty[:2000])
    LOG_LINES.append(pretty)


def write_log() -> Path:
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "tool_calling.txt"
    path.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    return path


def run(user_message: str, max_turns: int = 10) -> str:
    # THE message array. This is the entire state of the agent. There is no
    # other memory. Every API call re-sends all of it, which is why token
    # growth becomes the central engineering problem later on.
    messages = [{"role": "user", "content": user_message}]

    for turn in range(max_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        log(f"\n\n═══ TURN {turn + 1} ═══")
        log(f"stop_reason: {response.stop_reason}")
        log(f"tokens: in={response.usage.input_tokens} out={response.usage.output_tokens}")
        dump("ASSISTANT RESPONSE (raw content blocks)",
             [b.model_dump() for b in response.content])

        if response.stop_reason != "tool_use":
            final = "".join(b.text for b in response.content if b.type == "text")
            log(f"\n\n>>> FINAL ANSWER: {final}")
            log(f">>> Message array ended up {len(messages) + 1} entries long.")
            return final

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            log(f"\n  ⚙  executing {block.name}({block.input})")
            result, is_error = run_tool(block.name, block.input)
            log(f"  ⚙  -> {result}{'  [ERROR]' if is_error else ''}")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Hit max_turns ({max_turns}) without a final answer")


if __name__ == "__main__":
    # This question needs BOTH tools, in order: get the date, then do math on
    # it. Watch the model sequence them across separate turns — it can't
    # compute the second call's arguments until it sees the first result.
    try:
        run("How many days are left in the current year? Give me the exact number.")
    finally:
        # Write it even if the loop blew up — the log is most useful on failure.
        print(f"\n--- log written to {write_log()}")

    # ── Things to try next, in rough order of what they teach ────────────────
    #
    # 1. "What's 15% of 240?" — easy enough that the model may skip the tool
    #    entirely. Tighten the description until it always calls it. This is
    #    how you learn descriptions are prompts.
    #
    # 2. "Calculate 5 / 0" — see the error path. The model reads the traceback
    #    and explains the problem instead of your program dying.
    #
    # 3. "What's 12*12, and also 15*15?" — parallel tool calls: two tool_use
    #    blocks in one assistant message, two results in one user message.
    #
    # 4. Delete get_current_time from TOOL_SCHEMAS but leave it in
    #    TOOL_FUNCTIONS, then ask for the date. The model can only see the
    #    schemas — capability it isn't told about doesn't exist.
    #
    # 5. Add a system prompt and watch how it changes tool-selection behavior
    #    without touching a single schema.