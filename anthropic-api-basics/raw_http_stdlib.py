"""
The same call with no third-party packages at all — standard library only.

    export ANTHROPIC_API_KEY=sk-ant-...
    python raw_http_stdlib.py
"""

import json
import os
import urllib.error
import urllib.request

body = json.dumps(
    {
        "model": "claude-haiku-4-5",
        "max_tokens": 512,
        "system": "You are a concise assistant. Answer in one short sentence.",
        "messages": [{"role": "user", "content": "What can you help me with?"}],
    }
).encode("utf-8")

request = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=body,
    headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read())
    print(data["content"][0]["text"])
    print(f"\ntokens: {data['usage']['input_tokens']} in / "
          f"{data['usage']['output_tokens']} out")
except urllib.error.HTTPError as e:
    # urllib raises on 4xx/5xx; Anthropic's JSON error is in the body.
    print(f"HTTP {e.code}")
    print(e.read().decode())
