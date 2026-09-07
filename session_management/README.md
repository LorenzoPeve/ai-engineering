# Session management — a bare-bones harness

The Messages API is stateless: every turn you resend the entire conversation.
A *harness* is the layer that owns that history. This is the smallest honest
version of one.

## The pieces

| file | job |
|---|---|
| `llm.py` | `LLM` — thin wrapper over the Messages API. Stateless by design; knows nothing about sessions. |
| `events.py` | The log types (`Event`, `SessionMeta`) and `to_messages()`, the pure projection from log → wire format. |
| `store.py` | The `Store` protocol + `JSONLStore` (one dir per session, append-only `.jsonl`). |
| `sqlite_store.py` | `SQLiteStore` — same protocol, two tables. |
| `session.py` | The harness: log → project → call → log. |
| `postgres_store.py` | `PostgresStore` — same protocol again, for when one process isn't enough. |
| `chat.py` | A REPL you can quit and resume. |
| `demo.py` | Narrated walkthrough. **Start here.** |

## The data model

**`sessions`** — `id`, `model`, `system`, `title`, `created_at`, `updated_at`.
One row per conversation; the thing you resume by.

**`events`** — `seq` (AUTOINCREMENT), `session_id`, `ts`, `type`, `payload` (JSON).
Append-only. `seq` gives total order, so replay is `ORDER BY seq` and never
depends on timestamp resolution.

There is deliberately **no `messages` table**. `events` is a *superset* of the
wire format — it also carries usage, errors, and later tool results and
compaction markers. `to_messages(events)` filters and projects it down to what
the API accepts. A materialized `messages` table would be a second source of
truth, free to drift from the first.

## Two rules worth internalizing

1. **Append-only.** No `update_event`, no `delete_event` in the protocol.
   On current models, thinking blocks are bound to the model that produced
   them and editing earlier turns invalidates them — a harness that rewrites
   history breaks. Log corrections as *new* events.
2. **The store is the source of truth.** `Session.messages()` re-reads from the
   store every turn instead of keeping a list in RAM. In-memory state is only
   ever a view. That is what makes resume-across-processes fall out for free.

Assistant turns are replayed as full **content blocks**, not flattened text —
thinking blocks must be echoed back unchanged, and `tool_use` blocks have to
stay paired with their `tool_result`.

## Choosing a model

The default comes from `ANTHROPIC_MODEL` in `.env` (currently
`claude-haiku-4-5-20251001`), so one line switches every script here. Override
for a single run with `--model`:

```bash
python session_management/chat.py --model claude-opus-5
```

`llm.py` shapes the request per model, because the API surface is not uniform:
adaptive thinking and `output_config.effort` exist on the current generation
(Opus 5, Sonnet 5, the 4.6+ family) and are **rejected with a 400** by Haiku 4.5
and older. Those models take a fixed `thinking.budget_tokens` instead, and no
`effort` at all — so `LLM` sends effort only where it's supported, and exposes
`thinking_budget` for the older path:

```python
LLM(thinking_budget=2048)     # Haiku 4.5: fixed budget, no effort
LLM(model="claude-opus-5")    # adaptive thinking + effort="high"
```

Resuming pins the model: `Session.resume()` restores `meta.model`, so a
conversation started on Opus keeps replaying on Opus even after you change the
env var. That's deliberate — thinking blocks in the log are bound to the model
that produced them.

## See it work

```bash
python session_management/demo.py --offline    # no API key, no cost
python session_management/demo.py              # same thing, real model
```

Five steps: start a session → two turns → **the log** → **the projection** →
throw the object away and resume from the id alone. Steps 3 and 4 are the
payoff — the same conversation printed twice, once as what you stored (6
events) and once as what the API sees (4 messages).

`--offline` swaps in a fake model that answers by quoting the history back at
you, so every reply tells you how many messages it was just handed. Watching
that number climb is the clearest demonstration of statelessness there is.

Then use it for real:

```bash
python session_management/chat.py                     # new session (sqlite)
python session_management/chat.py --backend jsonl     # flat files instead
python session_management/chat.py --list
python session_management/chat.py --resume sess_ab12cd34ef56
python session_management/chat.py --log sess_ab12cd34ef56
python session_management/chat.py --no-memory         # harness off, endpoint raw
python session_management/chat.py --show-payload      # print each request body
```

`--show-payload` prints the exact JSON body of every request to stderr before
it goes out — messages array, system prompt, and the per-model `thinking` /
`output_config` shaping from `llm.py`. It ends with a count of the messages on
the wire, so you can watch the resend grow (or stay pinned at 1 under
`--no-memory`). Pair it with `--no-memory` to see the two shapes side by side,
or redirect stderr to keep the transcript clean:
`python session_management/chat.py --show-payload 2> payloads.log`.

Watch `input_tokens` climb in the `usage` events across a conversation — that
is the stateless resend, in numbers. It's also why prompt caching exists.

`--no-memory` sends only the current turn. Tell it your name, ask for it back,
and it has no idea — the API never remembered anything, the harness did. Every
turn is still logged, so `--log SESSION_ID` shows the full history the model
was never given, and `input_tokens` stays flat instead of climbing.

Data lands in `session_management/data/` (gitignored).

## Using Postgres

SQLite and JSONL are single-writer and single-machine. The moment two
processes share a session — a web request and a background job, two workers
behind a load balancer — you want a real database. `PostgresStore` is the same
Protocol with `%s` placeholders, `BIGSERIAL` instead of `AUTOINCREMENT`, and
`JSONB` instead of a TEXT column you have to `json.loads()` yourself.

**1. Install the driver** (kept out of `requirements.txt` — the import in
`postgres_store.py` is lazy, so the other backends don't need it):

```bash
pip install "psycopg[binary]"
```

**2. Get a Postgres.** Throwaway one in Docker:

```bash
docker run -d --name harness-pg \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=harness \
  -p 5432:5432 postgres:16
```

**3. Point at it.** Defaults to `postgresql://postgres:postgres@localhost:5432/harness`,
override with `DATABASE_URL` (any managed Postgres — Neon, Supabase, RDS — works
the same; append `?sslmode=require` for hosted ones):

```bash
export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
```

**4. Run:**

```bash
python session_management/demo.py --offline --backend postgres
python session_management/chat.py --backend postgres --list
```

The tables create themselves on first connect. To inspect the log in SQL:

```sql
SELECT seq, type, payload->>'content' FROM events
WHERE session_id = 'sess_...' ORDER BY seq;

-- JSONB means you can query INTO the payload. Total spend per session:
SELECT session_id,
       SUM((payload->>'input_tokens')::int)  AS input_tokens,
       SUM((payload->>'output_tokens')::int) AS output_tokens
FROM events WHERE type = 'usage' GROUP BY session_id;
```

That second query is the argument for keeping `usage` in the same append-only
log as the messages, rather than off in some metrics system: cost and
conversation are one ordered history, and you can ask questions across both.

Tear the container down with `docker rm -f harness-pg`.

## Where the abstraction earns its keep

Three backends, and `session.py` imports none of them — it only knows the
`Store` protocol in `store.py`. Adding a fourth (Redis, DynamoDB, a plain
in-memory dict for tests) means writing six methods and changing nothing above
that line. If you only take one structural idea from this directory, take that
one: the harness depends on an *interface* for persistence, never a database.
