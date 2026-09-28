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

**Two vendors are built: `mock` and `gemini`.** The registry also accepts
`leonardo`, `tavily` and `supabase`, and then fails to import an adapter that
does not exist in this build. Those are Protocol seams — the place a fourth
vendor would slot in without touching a node or a service — not working
integrations, and selecting one fails at startup.

| Variable | Built | Accepted but not implemented |
|---|---|---|
| `LLM_PROVIDER` | `mock` · `gemini` | — |
| `IMAGE_PROVIDER` | `mock` · `gemini` | `leonardo` |
| `EMBEDDING_PROVIDER` | `mock` · `gemini` | — |
| `STORAGE_PROVIDER` | `local` | `supabase` |
| `SEARCH_PROVIDER` | `none` | `tavily` |

Selecting a provider without its credential **fails at startup**, not at the
first user request — a missing key is a configuration mistake, and discovering
it three minutes into a demo is the worst possible time. So does a blank model
id. Whether an id names a model that *exists* can only be answered by the
provider; that is what the smoke tests below are for.

### Gemini

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_LLM_MODEL` | `gemini-3.8-flash` | Reasoning, text and multimodal. A stable id, not a `-preview` or `-latest` alias: a plan that changes between two runs is not reproducible. Must accept image input — reference analysis, evaluation and the Brand Guardian all hand it one. |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Nano Banana 2, the current model. Separate capability, separate cadence — changing the reasoning model must never change what draws the plate. `gemini-2.5-flash-image` is legacy and the docs recommend transitioning off it. |
| `IMAGE_MAX_RETRIES` | `1` | Extra attempts after a *retryable* image failure. Every attempt is billable; capped at 3. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Stable. `gemini-embedding-2-preview` exists and is not used here. |
| `GEMINI_EMBEDDING_DIMENSIONS` | `1536` | Width **requested of the API**, never trimmed afterwards. |

The key is read once, in `app/config.py`, and reaches nothing but the adapter
that authenticates with it. It never appears in a response, a log line, a
`ProviderError.detail` (redaction is by shape, in `ProviderError.__init__`) or
anything in the browser bundle. The smoke tests print a four-character suffix
so two people can tell whether they hold the same key; nothing prints more.

Embedding dimensions are checked at startup: a provider whose vector width
disagrees with `brand_chunks.embedding` is caught at boot rather than at the
first retrieval, and the Gemini adapter checks *again* against what the API
actually returned. A vector of the wrong width is reported, never truncated —
trimming would turn a misconfiguration into retrieval that is merely bad,
which is far harder to diagnose than a boot failure.

Switching `EMBEDDING_PROVIDER` or `GEMINI_EMBEDDING_DIMENSIONS` after documents
have been ingested invalidates every stored vector — they were produced by a
different model or a different width. Re-ingest, or keep both fixed for the
life of the database.

### Verifying a credential

Three scripts, and the only code in this repository that deliberately reaches
an external service. Each makes one controlled request, prints a safe summary,
never prints the key, and exits `0` verified / `1` credential problem / `2`
something else:

```bash
cd backend
LLM_PROVIDER=gemini       uv run python scripts/gemini_llm_smoke_test.py
EMBEDDING_PROVIDER=gemini uv run python scripts/gemini_embedding_smoke_test.py
IMAGE_PROVIDER=gemini     uv run python scripts/gemini_smoke_test.py
```

Run them before a deploy that sets `*_PROVIDER=gemini`. The reasoning and
embedding scripts pass against a Google AI Studio key; the image one does not
— see §9.

One trap worth knowing: an exported `GEMINI_API_KEY` in your shell **beats**
the one in `backend/.env`, because environment variables outrank the env file.
A new key that appears not to work is usually an old one still exported.

## 6. Authentication

Two providers, selected by `AUTH_PROVIDER`, behind one seam. The provider
answers only *who is this?*; membership and organization scope are resolved
separately in `app/api/deps.py` and are identical in both modes (ADR-002).

### Development — `dev_stub`

Authenticates **every caller as the same user** and ignores the credential. It
raises at construction when `APP_ENV=production`, so a production deploy cannot
start with it by accident. The offline demo depends on this and needs no
identity provider, no keys and no network.

### Production — `supabase`

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | The project. Also used by storage. |
| `SUPABASE_ANON_KEY` | The publishable key. Identifies the project when verifying a caller's token. |

Both are required when `AUTH_PROVIDER=supabase`; a missing one is a **startup
failure**, not a 401 that reads to a user like a bad password.

**The anon key is public by design.** It carries no privilege of its own and is
inlined into the browser bundle so the sign-in page can reach Supabase
directly. `SUPABASE_SERVICE_ROLE_KEY` is storage's alone — the auth provider
never sends it, and it must never reach a browser.

**How a token is verified.** The bearer credential is sent to Supabase's own
`GET /auth/v1/user`; `200` means valid. This is the check Supabase documents
for server-side validation, and it is chosen over verifying the JWT locally
with the project's shared secret — which Supabase recommends against. The
trade is a network call per request to a single-region Auth server, bounded by
a 30-second cache keyed by a digest of the token (never the token). The gain is
that a signed-out or revoked session stops working immediately rather than at
token expiry.

**Identity is the subject**, `users.auth_subject` ← Supabase's `id`. There is
no fallback to email, because an email can be reassigned between people and
treating it as identity is how one person inherits another's memberships
(M1_SECURITY_AUDIT §A-1). An account with no email is refused rather than
provisioned with a placeholder.

> **Verified offline only.** The provider is fully covered by tests driving a
> fake Supabase through `respx`, and `AUTH_PROVIDER=supabase` with
> `APP_ENV=production` is proven to construct. It has **not** been run against
> a real Supabase project. Treat the first deploy as the verification step.

### Serving media to a browser — `MEDIA_URL_SECRET`

Neither header above reaches an `<img src>`: a browser cannot set
`Authorization` or `X-Organization-Id` on an image, a video or a download link.
So every media `url` the API returns carries a short-lived signature naming one
row, one organization and one user (ADR-017, `app/api/media_links.py`). The byte
route verifies it, re-checks membership, and then resolves the row through the
organization-scoped repository exactly as a header-authenticated request does.

**Set `MEDIA_URL_SECRET` in production.** The app refuses to start without it
when `APP_ENV=production`, for a reason worth stating: unset, each process
generates its own key at startup, and behind a load balancer instance A cannot
verify a link instance B signed. The symptom is images that appear on one
refresh and not the next — an intermittent bug that looks like flaky storage and
is not. Generate one per environment and give every instance the same value:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Rotating it invalidates every link already on a rendered page, so a user's open
tab shows broken images until they reload. Rotate on a deploy, not mid-session,
and treat it as a secret: it is a signing key, and anyone holding it can mint a
link to any row whose id they know.

`MEDIA_URL_TTL_S` (default 900) is how long a link lives. Long enough to render
a page and open an image in a new tab; short enough that a link caught in an
access log, a proxy buffer or a `Referer` header is worthless by the time
anyone reads it. Raising it past an hour trades that away for very little.

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
# Shared by every instance. The app refuses to start without it in production.
MEDIA_URL_SECRET=…
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
- **Only two vendors are implemented.** `mock` and `gemini`. `leonardo`,
  `tavily` and `supabase` storage are names the registry accepts and then
  fails to import — Protocol seams kept honest by the fact that selecting one
  fails at boot rather than at the first request.
- **Live Gemini image generation is still unverified**, though the defect
  that blocked it is fixed. Reasoning and embeddings are verified against a
  Google AI Studio key (2026-09-23); images are not. Two independent causes
  were found, and only one of them was ours:
  1. **The adapter asked for a format the provider does not produce.** It
     hardcoded `response_format.mime_type = "image/png"`, and both
     `gemini-2.5-flash-image` and `gemini-3.1-flash-image` reject that with
     `400 invalid_request` — *"Supported values: 'image/jpeg'"*. **Fixed:**
     `RESPONSE_MIME_TYPE = "image/jpeg"` in
     `app/providers/gemini/image.py`, covered by regression tests that fail if
     it is ever set back. This governs the *plate only* — deterministic
     rendering is still PNG, and composition still outputs PNG (ADR-014).
  2. **Image generation is not available on the free tier.** `429` —
     *"Rate limit exceeded for model gemini-3.1-flash-image (limit: 0 input
     tokens per minute on Free Tier). Please upgrade your tier at
     https://ai.dev/rate-limit"* — returned after ~165 seconds of queueing.
     A billing-enabled key is required, and nothing in this repository can
     work around it.

     **That queueing delay matters operationally.** The 429 arrives *after*
     `GENERATION_TIMEOUT_S` (120s), so a quota-blocked account surfaces to
     users as "did not respond in time" rather than a rate-limit message, and
     with `IMAGE_MAX_RETRIES=1` it costs two full timeouts before failing. If
     you run against a tier that queues, raise the timeout above the
     provider's queueing time so the real reason reaches the job row.

  So the adapter is believed correct and is *not* proven so: the fix was
  verified against a fake SDK client and a JPEG plate all the way through
  composition, never against the live API. Run
  `scripts/gemini_smoke_test.py` on a billed key before claiming otherwise.
  Mock image generation is unaffected and remains the guaranteed path.
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
