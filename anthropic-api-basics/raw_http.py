"""
The same call without the SDK: one HTTPS POST, one JSON response.

The server keeps no state between calls, which is why the whole conversation
goes in `messages` every time.

Run it:
    python raw_http.py
"""

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

URL = "https://api.anthropic.com/v1/messages"


def main() -> None:
    response = httpx.post(
        URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            # Required. Pins the schema, not the model.
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-haiku-4-5",
            "max_tokens": 512,
            "system": "You are a concise assistant. Answer in one short sentence.",
            "messages": [{"role": "user", "content": "What can you help me with?"}],
        },
        # httpx defaults to 5s, too short for a model call.
        timeout=60.0,
    )

    print(f"HTTP {response.status_code}\n")
    # httpx does not raise on 4xx/5xx; the error body is JSON too.
    if response.status_code != 200:
        print(json.dumps(response.json(), indent=2))
        return

    data = response.json()
    print(json.dumps(data, indent=2))

    # The dicts the SDK would have turned into TextBlock objects.
    print("\n--- just the text ---")
    for block in data["content"]:
        if block["type"] == "text":
            print(block["text"])

    print(f"\n--- stop_reason: {data['stop_reason']}")
    print(
        f"--- tokens: {data['usage']['input_tokens']} in / "
        f"{data['usage']['output_tokens']} out"
    )



if __name__ == "__main__":
    main()
