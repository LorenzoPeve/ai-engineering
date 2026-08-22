"""
The simplest Anthropic API call, using the official SDK.

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
    # Anthropic() reads ANTHROPIC_API_KEY from the environment.
    client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system="You are a concise assistant. Answer in one short sentence.",
        messages=[
            {"role": "user", "content": "In one sentence: what is the Anthropic Messages API?"}
        ],
    )

    # content is a list of blocks (text, thinking, tool_use, ...), not a string.
    for block in response.content:
        if block.type == "text":
            print(block.text)

    print(f"\n--- stop_reason: {response.stop_reason}")
    print(
        f"--- tokens: {response.usage.input_tokens} in / "
        f"{response.usage.output_tokens} out"
    )

    # Save to json
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "api.json").write_text(
        response.model_dump_json(indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
