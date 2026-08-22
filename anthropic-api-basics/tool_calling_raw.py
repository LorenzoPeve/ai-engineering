"""
Tool calling at the wire level: tools are just JSON in the request body.

One POST, one response, saved to output/.

Run it:
    python tool_calling_raw.py
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

URL = "https://api.anthropic.com/v1/messages"

TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'Austin'"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city"],
        },
    }
]


def main() -> None:
    payload = {
        "model": "claude-haiku-4-5",
        "max_tokens": 512,
        "tools": TOOLS,
        "messages": [{"role": "user", "content": "What's the weather in Austin?"}],
    }

    response = httpx.post(
        URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=60.0,
    )

    print(f"HTTP {response.status_code}\n")
    data = response.json()
    print(json.dumps(data, indent=2))

    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "tool_calling_raw.json"
    out_path.write_text(
        json.dumps({"request": payload, "response": data}, indent=2),
        encoding="utf-8",
    )
    print(f"\n--- saved to {out_path}")

    if response.status_code != 200:
        return

    print(f"--- stop_reason: {data['stop_reason']}")
    for block in data["content"]:
        if block["type"] == "tool_use":
            print(f"--- wants: {block['name']}({block['input']})  id={block['id']}")


if __name__ == "__main__":
    main()
