"""
The simplest possible Anthropic API call — a smoke test for your API key.

What it does
------------
1. Loads ANTHROPIC_API_KEY from the repo-root .env file (git-ignored).
2. Sends one message to Claude via the official `anthropic` SDK.
3. Prints the reply, plus the token usage so you can see what a call costs.

Run it:
    pip install -r requirements.txt
    python hello_claude.py
"""

from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = "claude-haiku-4-5"


def main() -> None:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system="You are a concise assistant. Answer in one short sentence.",
        messages=[
            {"role": "user", "content": "What can you help me with?"}
        ],
    )
    for block in response.content:
        if block.type == "text":
            print(block.text)

    print(f"\n--- stop_reason: {response.stop_reason}")
    print(
        f"--- tokens: {response.usage.input_tokens} in / "
        f"{response.usage.output_tokens} out"
    )


if __name__ == "__main__":
    main()
