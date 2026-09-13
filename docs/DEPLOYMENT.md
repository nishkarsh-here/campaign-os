# DEPLOYMENT.md — running campaign-os somewhere other than a laptop

Two processes and a database. No broker, no worker fleet, no Docker required —
background work runs in the API process (ADR-012), which is the trade this
product made deliberately and whose limits are stated under
[What this deployment cannot do](#what-this-deployment-cannot-do).

```
┌────────────┐        ┌──────────────────┐        ┌──────────────────────┐
│  Next.js   │ ─────► │  FastAPI (API +  │ ─────► │  PostgreSQL 16+      │
│  frontend  │  HTTP  │  background work)│        │  + pgvector          │
└────────────┘        └────────┬─────────┘        └──────────────────────┘
                               │
                               ▼
                        object storage
                     (local disk or Supabase)
```

The browser talks only to the API. It never holds a provider key, never reaches
object storage directly, and never receives a storage key it could dereference.

---

## 1. Database

PostgreSQL **16 or newer** with three extensions available: `pgcrypto`,
`citext`, `vector` (pgvector ≥ 0.7). Managed Postgres on Supabase, Neon, Railway
and RDS all ship these; the migration enables them itself, so the role running
migrations needs `CREATE EXTENSION` rights the first time.

```bash
createdb campaign_os
cd backend && uv run alembic upgrade head
```

`alembic upgrade head` is idempotent and safe to run on every deploy. Run it
**before** the new API process starts, not from inside it — two instances
racing the same migration is the one thing this setup cannot recover from.

The LangGraph checkpoint tables are **not** managed by Alembic. The API creates
them at startup (`ensure_checkpoint_tables`), because `setup()` issues
`CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction. Alembic's
`env.py` excludes them; without that exclusion, autogenerate proposes dropping
every paused conversation.

## 2. Backend

Python 3.13, dependencies managed by `uv`.

```bash
cd backend
uv sync --no-dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

A host that injects `$PORT` (Railway, Render, Fly) needs nothing else. Set
`API_HOST=0.0.0.0` so the process is reachable from outside its container —
the `127.0.0.1` default is a local-development safety, and is the single most
common reason a first deploy answers nothing.

**Health.** `GET /v1/health` reports process, database and the selected
providers. It returns `200` with `"status": "degraded"` when the database is
unreachable rather than failing to respond, so a platform health check
distinguishes "the process is up and the database is not" from "the process is
gone".

**Startup is defensive on purpose.** A missing database does not stop the
process from booting; `/health` reports it. A container that exits during boot
tells an operator far less than one that starts and says what is wrong.

## 3. Frontend

```bash
cd frontend
npm ci
API_BASE_URL=https://api.example.com npm run build
npm run start      # or deploy the build to Vercel
```

`API_BASE_URL` is the only thing the frontend needs, and it is read at build
time. It must be an origin the **browser** can reach — not an internal service
name — because every API call and every image `src` is made by the browser.

No `NEXT_PUBLIC_*` variable exists in this project, and none should be added:
the frontend has no secrets because it talks to nothing but our API.

## 4. Storage

`STORAGE_PROVIDER=local` writes to `LOCAL_STORAGE_DIR`. That is correct for a
single instance with a persistent volume, and **wrong for more than one** —
instance A cannot serve an asset instance B wrote. Behind more than one API
instance use `STORAGE_PROVIDER=supabase` with a bucket, or give every instance
the same network volume.

Storage keys are generated, never derived from a filename, and always carry the
organization and campaign as a prefix. Nothing serves a key taken from a
request: every byte-serving route resolves a scope-checked row first and reads
*its* key.

## 5. Providers

| Variable | Effect |
|---|---|
| `LLM_PROVIDER` | `mock` \| `gemini` |
| `IMAGE_PROVIDER` | `mock` \| `gemini` \| `leonardo` |
| `EMBEDDING_PROVIDER` | `mock` \| `gemini` |
| `SEARCH_PROVIDER` | `none` \| `tavily` |

Selecting a provider without its credential **fails at startup**, not at the
first user request — a missing key is a configuration mistake, and discovering
it three minutes into a demo is the worst possible time.

Embedding dimensions are checked at startup too: a provider whose vector width
disagrees with the column is caught at boot rather than at the first retrieval.

Switching `EMBEDDING_PROVIDER` after documents have been ingested invalidates
every stored vector — they were produced by a different model. Re-ingest, or
keep the provider fixed for the life of the database.

## 6. Authentication

`AUTH_PROVIDER=dev_stub` authenticates **every caller as the same user**. It
raises at construction when `APP_ENV=production`, so a production deploy cannot
start with it by accident. That guard is the whole of the protection — set
`AUTH_PROVIDER=supabase` and `APP_ENV=production` together.

## 7. Environment variables

`.env.example` is the complete list, marked `[required]`, `[optional]`,
`[development]`, `[demo]` and `[provider]`. `tests/test_config.py` asserts it
stays in step with `Settings` in both directions — a setting nobody documented,
and a documented knob nothing reads, both fail the suite.

Minimum for a production deploy:

```bash
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://…
DATABASE_URL_SYNC=postgresql://…
CORS_ORIGINS=https://app.example.com
API_HOST=0.0.0.0
AUTH_PROVIDER=supabase
STORAGE_PROVIDER=supabase
SUPABASE_URL=…
SUPABASE_SERVICE_ROLE_KEY=…
LLM_PROVIDER=gemini
IMAGE_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=…
```

## 8. Demonstration deploy

A demo instance is a different thing from a production one and says so:

```bash
DEMO_MODE=true
LLM_PROVIDER=mock
IMAGE_PROVIDER=mock
EMBEDDING_PROVIDER=mock
```

`DEMO_MODE=true` **refuses to start** with any non-mock provider, so a
demonstration cannot come to depend on an external service. The mode is
reported on `/v1/health` and the interface shows a badge, so nobody watching
has to guess whether the output in front of them came from a real model.

Seed the canonical campaign after migrating:

```bash
cd backend && uv run python scripts/seed_demo.py --reset
```

## 9. What this deployment cannot do

Stated plainly, because a limitation you know about is a trade and one you
discover is an outage.

- **Background work runs in the API process.** Generation, evaluation and brand
  checks are `asyncio` tasks, not queue workers (ADR-012). They do not survive a
  restart. At startup the API marks anything a previous process abandoned as
  `FAILED` with "interrupted by a server restart", so it is visible and
  retryable rather than a spinner that never resolves — see
  `app/services/reconcile.py`. A wrong-but-honest failure beats a permanent
  spinner; the work is cheap to redo.
- **That reconciliation is a heuristic across instances.** It only touches rows
  older than the generation timeout plus five minutes, which is long enough that
  a job genuinely running elsewhere is never inside the window. With a single
  instance it is exact. With several it is very nearly exact, and making it a
  guarantee would need leases and a coordinator — which is the worker
  architecture this product deliberately does not have.
- **Local storage does not work behind more than one instance.** See §4.
- **There is no rate limiting.** Provider spend is bounded by the per-batch
  image count and the timeouts, not by request volume. Put a rate limit at the
  edge before exposing this publicly.
- **`/v1/docs` is served in every environment.** It documents the API, not the
  data, but disable it at the edge if you would rather not publish the shape.
- **Long-running jobs have no progress detail.** A job is `PENDING`, `RUNNING`,
  or terminal. There is no percentage, because there is nothing underneath that
  could honestly produce one.

## 10. Upgrades

1. `alembic upgrade head` against the new code, before it starts.
2. Deploy the backend.
3. Deploy the frontend.

Migrations are additive. Nothing in this project drops a column that a running
older instance still reads, so a rolling deploy is safe; a migration that ever
needs to would have to be split across two releases.
