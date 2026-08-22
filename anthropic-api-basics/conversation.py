"""
Turn accumulation: how `messages` grows across an agentic conversation.

The API is STATELESS. There is no conversation id, no server-side history.
Every POST resends the entire transcript. "Keeping track of the conversation"
is therefore just one discipline: append the right thing, in the right order,
to a plain Python list.

The three append rules, which is the whole lesson:

  1. Assistant turn -> append data["content"] VERBATIM. The entire list, every
     block, unmodified. Not content[0], not the text you extracted. If the
     model returned [text, tool_use, tool_use], all three go back.

  2. Tool results -> one user message containing ALL tool_result blocks, each
     matched to its tool_use by `tool_use_id`. Splitting them across several
     user messages is legal but teaches the model to stop calling in parallel.

  3. Then loop. If stop_reason is still "tool_use", you are not done.

Run it:
    python conversation.py
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5"          # matching tool_calling_raw*.py; any model works
MAX_TOKENS = 1024

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
            "properties": {"city": {"type": "string"}},
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

# Fake tool implementations. Real ones would hit an API; the shape of what you
# return is what matters here — a string, or a JSON-dumped object.
FAKE_WEATHER = {"Austin": "97F, sunny", "Denver": "58F, snow flurries",
                "Miami": "88F, thunderstorms"}
FAKE_TIME = {"Austin": "3:42 PM CDT (UTC-5)", "Denver": "2:42 PM MDT (UTC-6)",
             "Miami": "4:42 PM EDT (UTC-4)"}


def execute_tool(name: str, tool_input: dict) -> str:
    """Dispatch on tool name. Returns a string — the `content` of a tool_result."""
    city = tool_input.get("city", "")
    if name == "get_weather":
        return FAKE_WEATHER.get(city, f"no data for {city}")
    if name == "get_timezone":
        return FAKE_TIME.get(city, f"no data for {city}")
    return f"unknown tool: {name}"


# ─────────────────────────────────────────────────────────────────────────────
# INSPECTION HELPERS
# Not part of the mechanism — they just make the growing list legible.
# ─────────────────────────────────────────────────────────────────────────────

def block_label(block) -> str:
    """One-line label for a content block, whatever its type."""
    if isinstance(block, str):
        return f"str({len(block)} chars)"

    kind = block["type"]
    if kind == "text":
        return f"text({block['text'][:40]!r}...)"
    if kind == "thinking":
        return f"thinking({len(block['thinking'])} chars)"
    if kind == "tool_use":
        return f"tool_use({block['name']} {json.dumps(block['input'])} id={block['id'][-6:]})"
    if kind == "tool_result":
        return f"tool_result(id={block['tool_use_id'][-6:]} -> {str(block['content'])[:30]!r})"
    return kind


def print_history(messages: list, note: str) -> None:
    """Show the whole transcript as it currently stands."""
    print(f"\n  ── messages[] after {note} — {len(messages)} message(s)")
    for i, msg in enumerate(messages):
        content = msg["content"]
        blocks = [content] if isinstance(content, str) else content
        head = f"    [{i}] {msg['role']:<9}"
        print(f"{head} {len(blocks)} block(s)")
        for b in blocks:
            print(f"{' ' * len(head)}   · {block_label(b)}")


def post(messages: list) -> dict:
    """One POST. Note that `messages` is the ONLY state we carry."""
    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "tools": TOOLS,
        "messages": messages,
    }
    response = httpx.post(URL, headers=HEADERS, json=payload, timeout=60.0)
    data = response.json()
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}\n{json.dumps(data, indent=2)}")
    usage = data["usage"]
    print(f"    -> stop_reason={data['stop_reason']}  blocks={len(data['content'])}  "
          f"in={usage['input_tokens']} out={usage['output_tokens']}")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# THE LOOP
# ─────────────────────────────────────────────────────────────────────────────

def send(messages: list, user_text: str, transcript: list) -> list:
    """
    Add one user turn and run it to completion, appending everything to
    `messages` in place. Returns the final assistant text.

    "To completion" means: keep going while stop_reason == "tool_use". A single
    user turn can cost several round trips.
    """
    print(f"\n{'═' * 74}\n  USER: {user_text}\n{'═' * 74}")

    # ── APPEND 1: the user turn. Plain string content is fine here; the API
    # normalizes it to [{"type": "text", ...}] server-side.
    messages.append({"role": "user", "content": user_text})
    print_history(messages, "user turn")

    hop = 0
    while True:
        hop += 1
        print(f"\n  POST #{hop} — sending {len(messages)} message(s)")
        data = post(messages)
        transcript.append({"request_messages": json.loads(json.dumps(messages)),
                           "response": data})

        # ── APPEND 2: the assistant turn, VERBATIM.
        #
        # This is the line people get wrong. `data["content"]` is the full list
        # of blocks. You append the list itself — you do NOT rebuild it from the
        # text you happened to care about, and you do NOT take content[0].
        #
        # Why verbatim matters: each tool_use block carries an `id`. The next
        # message's tool_result blocks reference those ids. Drop a tool_use
        # block and its tool_result becomes an orphan -> 400. Drop the text
        # block and the model loses what it said. Same for thinking blocks:
        # they must be echoed back unchanged or the model's reasoning vanishes
        # from context (and on thinking-enabled models, that's a 400 too).
        messages.append({"role": "assistant", "content": data["content"]})
        print_history(messages, "assistant turn")

        if data["stop_reason"] != "tool_use":
            # end_turn (or max_tokens / refusal). Nothing to execute; done.
            final = "".join(b["text"] for b in data["content"] if b["type"] == "text")
            print(f"\n  FINAL: {final}")
            return final

        # ── Execute every tool_use block in the assistant message.
        # Filter by type — the list also holds text and possibly thinking.
        calls = [b for b in data["content"] if b["type"] == "tool_use"]
        print(f"\n  executing {len(calls)} tool call(s)")

        results = []
        for call in calls:
            output = execute_tool(call["name"], call["input"])
            print(f"    {call['name']}({json.dumps(call['input'])}) -> {output}")
            results.append({
                "type": "tool_result",
                # The join key. This is why the assistant block had to survive
                # verbatim: `id` there == `tool_use_id` here.
                "tool_use_id": call["id"],
                "content": output,
                # For a failure, still return the block, with:
                #   "is_error": True, "content": "TimeoutError: ..."
                # Silently dropping it is the one thing that will 400 you.
            })

        # ── APPEND 3: ALL results in ONE user message.
        #
        # Note the role: "user". Tool results are user-role content, even
        # though no human wrote them — the "user" role really means "whoever
        # is driving the loop", which is your code.
        #
        # And note it's one message holding N blocks, not N messages. Both are
        # accepted, but splitting them nudges the model away from parallel
        # calls on later turns.
        messages.append({"role": "user", "content": results})
        print_history(messages, "tool results")
        # Loop back around: POST the now-longer list.


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)

    messages: list = []          # ← the entire conversation state. That's it.
    transcript: list = []        # every request/response pair, for the JSON dump

    # Turn 1: needs parallel tool calls, so the assistant message will hold
    # several tool_use blocks and you can watch them all get answered at once.
    send(messages, "Compare the weather in Austin, Denver, and Miami.", transcript)

    # Turn 2: a follow-up that is only answerable from history. Nothing was
    # sent to a server to "remember" it — the words are still in `messages`,
    # which is why it works.
    send(messages, "Which of those did you say was coldest? One word.", transcript)

    # Turn 3: needs a NEW tool call, on a city named only in the earlier turn.
    # Resolving "the coldest one" -> Denver happens because the whole history
    # is in the prompt.
    send(messages, "What time is it in that coldest city right now?", transcript)

    out_path = out_dir / "conversation.json"
    out_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

    print(f"\n\n{'═' * 74}\n  SUMMARY\n{'═' * 74}")
    print(f"  user-visible turns : 3")
    print(f"  HTTP requests      : {len(transcript)}")
    print(f"  messages[] length  : {len(messages)}")
    print(f"  final input_tokens : {transcript[-1]['response']['usage']['input_tokens']}")
    print("\n  Roles in order:")
    print("    " + " → ".join(m["role"] for m in messages))
    print(f"\n--- full request+response history saved to {out_path}")

    # ── Things to try ────────────────────────────────────────────────────────
    #
    # 1. Replace the verbatim append with only the text block:
    #        messages.append({"role": "assistant", "content":
    #            [b for b in data["content"] if b["type"] == "text"]})
    #    Read the 400. It names the unmatched tool_use_id. That error message
    #    is the best available explanation of why you append verbatim.
    #
    # 2. Drop one entry from `results` before appending. Same 400, opposite
    #    direction: a tool_use with no tool_result.
    #
    # 3. Split the results into one user message per block. It still works —
    #    then watch turn 3 and see whether the model still batches calls.
    #
    # 4. Watch input_tokens across the POSTs in the printed output. It only
    #    goes up, because you resend everything every time. That monotonic
    #    climb is the entire cost argument for prompt caching and for context
    #    editing / compaction.
    #
    # 5. Truncate history to simulate a naive window — messages[-4:] before
    #    POSTing. Turn 2 breaks. Truncating a transcript that contains tool
    #    pairs is not as simple as slicing: you must keep each tool_use with
    #    its tool_result.


if __name__ == "__main__":
    main()
