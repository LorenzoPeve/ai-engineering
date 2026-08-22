# Anthropic API Basics

The smallest useful Anthropic API example: one call, one response, fully commented.

## Setup

The API key is read from the repo-root `.env` file (git-ignored, so the key is
never committed):

```
ANTHROPIC_API_KEY=sk-ant-...
```

Install the dependencies and run it:

```bash
pip install -r requirements.txt
python hello_claude.py
```

## What the example shows

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
