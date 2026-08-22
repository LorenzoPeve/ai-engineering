# Anthropic API Basics

The smallest useful Anthropic API examples: one call, one response, fully commented.
Three files, from bare metal up to the SDK — read them in this order.

| File | Dependencies | What it teaches |
|---|---|---|
| `raw_http_stdlib.py` | none (stdlib `urllib`) | There is no magic: one POST, one JSON reply |
| `raw_http.py` | `httpx` | Same call with a normal HTTP library, error bodies shown |
| `hello_claude.py` | `anthropic` | What the SDK adds on top: typed objects, retries, auth |

## Setup

The API key is read from the repo-root `.env` file (git-ignored, so the key is
never committed):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Install the dependencies and run it:

```bash
pip install -r requirements.txt
python raw_http_stdlib.py   # first principles
python raw_http.py          # raw JSON, pretty-printed
python hello_claude.py      # the SDK version
```

`raw_http_stdlib.py` reads the key from the environment directly, so for that
one: `export ANTHROPIC_API_KEY=sk-ant-...` (or run it as
`ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY ../.env | cut -d= -f2) python raw_http_stdlib.py`).

## The entire API surface, in one shell command

No Python at all — this is exactly what all three scripts do:

```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-haiku-4-5",
    "max_tokens": 512,
    "messages": [{"role": "user", "content": "What can you help me with?"}]
  }'
```

Four headers-and-body facts worth memorizing:

- **`x-api-key`**, not `Authorization: Bearer` — Anthropic is unusual here.
- **`anthropic-version: 2023-06-01`** is required and pins the *schema*, not the model.
- **`messages`** is the whole conversation, resent every call. The server is stateless.
- **`max_tokens`** is required, and caps only the *response* length.

## What the SDK example shows

| Concept | Where |
|---|---|
| Loading the key from `.env` without hardcoding it | `load_dotenv(...)` |
| Creating a client (`Anthropic()` reads the env var itself) | `client = anthropic.Anthropic()` |
| The single endpoint everything goes through | `client.messages.create(...)` |
| `system` — standing instructions for the model | request args |
| `messages` — the conversation history list | request args |
| `max_tokens` — hard cap on response length | request args |
| Responses are a *list of content blocks*, not a string | the `for block in response.content` loop |
| Token usage / why the response ended | `response.usage`, `response.stop_reason` |

## Expected output

```
The Anthropic Messages API is a single HTTP endpoint for sending a conversation
to Claude and getting a reply back.

--- stop_reason: end_turn
--- tokens: 34 in / 28 out
```

## Next steps

- Uses `claude-haiku-4-5`, the cheapest current model ($1 / $5 per million
  input / output tokens). Swap `MODEL` for `claude-sonnet-5` or `claude-opus-5`
  to compare quality, cost, and speed.
- Append the model's reply to `messages` to make it multi-turn.
- Use `client.messages.stream(...)` to print tokens as they arrive.
