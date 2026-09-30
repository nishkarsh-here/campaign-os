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
                         local disk volume
                        (LOCAL_STORAGE_DIR)
```

**One frontend, one backend, one database, one volume.** That is the whole
architecture, and §4 explains why the backend is currently *one* rather than
several. Nothing here needs a broker, a worker fleet, a cache or object storage,
and adding any of them would be adding infrastructure the code does not use.

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

A host that injects `$PORT` (Railway, Render, Fly) needs nothing else.

**Bind address is a `uvicorn` argument, not a setting.** `--host 0.0.0.0` in the
command above is what makes the process reachable from outside its container,
and it is the single most common reason a first deploy answers nothing.
`API_HOST` and `API_PORT` exist in `Settings` and no code reads them — they
document the intended local defaults and nothing more, so setting `API_HOST` in
the environment changes nothing (audit finding P-2). Pass the flags.

**Health.** `GET /v1/health` reports process, database and providers. It returns
`200` with `"status": "degraded"` rather than failing to respond, so a platform
health check distinguishes "the process is up and the database is not" from "the
process is gone".

Providers are reported twice over, because a name and a capability are different
things. `providers` is what each seam is *configured* for; `provider_status` is
whether that adapter actually **constructed** — `ok` or `unavailable` — and an
unavailable one degrades the overall status. This endpoint used to echo the
configured names alone and answer `ok`, which made `STORAGE_PROVIDER=supabase`
look like a working integration. Construction is offline, so `ok` means the
adapter exists and is configured; whether the vendor is reachable is only ever
proved by calling it.

**Startup is defensive on purpose.** A missing database does not stop the
process from booting; `/health` reports it. A container that exits during boot
tells an operator far less than one that starts and says what is wrong.

## 3. Frontend

```bash
cd frontend
npm ci
API_BASE_URL=https://api.example.com npm run build
npm run start      # or deploy the build to a static/Node host
```

**`API_BASE_URL` is required at build time, and the build refuses without it.**
`next build` substitutes the value into the client JavaScript, so it is fixed
when the artefact is made and no runtime environment variable can correct it
afterwards. It must be an origin the **browser** can reach — not an internal
service name, not a container name — because every API call and every image
`src` is made by the browser.

It used to fall back to `http://127.0.0.1:8000`, which produced a site that
built cleanly, loaded perfectly and could reach nothing: the browser resolves
that against the *visitor's* machine. `next.config.mjs` now throws instead, and
also refuses a loopback origin unless `ALLOW_LOOPBACK_API_BASE_URL=true` says
the build really is a local smoke test. `src/lib/build-config.test.ts` asserts
both refusals.

**With Supabase auth, the frontend needs two more at build time** —
`SUPABASE_URL` and `SUPABASE_ANON_KEY` — because the browser signs in against
Supabase directly and only then calls our API with the resulting token. They are
deliberately *not* required by the build: without them `isSupabaseConfigured()`
is false and the sign-in screen explains itself rather than showing a form that
cannot work, which is what keeps the offline demo buildable. **If you deploy the
backend with `AUTH_PROVIDER=supabase` and build the frontend without these two,
nobody can sign in** and the screen will say so.

No `NEXT_PUBLIC_*` variable exists in this project, and none should be added.
The anon key is publishable by design; `SUPABASE_SERVICE_ROLE_KEY` is
server-side only and `next.config.mjs` does not expose it — asserted by a test.

## 4. Storage

`STORAGE_PROVIDER=local` writes to `LOCAL_STORAGE_DIR`, and **`local` is the
only storage provider this build has** (§5). That is correct for a single
instance with a persistent volume, and **wrong for more than one** — instance A
cannot serve an asset instance B wrote.

### The deployment constraint, plainly

**Run exactly one backend instance, unless every instance mounts the same
filesystem.** Uploaded brand documents, generated plates and rendered final
assets are files on that volume, and the byte-serving routes read them from the
instance that receives the request. With two instances and separate disks, an
asset uploaded through one is a 404 through the other — intermittently, which
is the worst way to find out.

So the first deployment is **one backend instance with a persistent volume**.
Two further points follow from the same fact:

* the volume must survive restarts and redeploys. A container filesystem that
  resets on deploy loses every uploaded document and rendered asset;
* horizontal scaling is not available until either a shared network volume is
  attached to every instance, or object storage is built behind the existing
  `StorageProvider` Protocol.

`STORAGE_PROVIDER=supabase` is that Protocol seam and has **no adapter in this
build** — the process refuses to start on it. It is where object storage would
slot in, not an option you can select today.

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

**Every one of the five seams is constructed at startup**, so selecting a name
with no adapter is a boot failure naming the variable, not a 500 at the first
upload. Until the M11 audit that was true only of the reasoning and embedding
providers; storage, image and search were built per request, so a bad
`STORAGE_PROVIDER` booted cleanly and failed on the first brand document.

Selecting a provider without its credential **fails at startup** too, not at the
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

### Connecting to a real Supabase project — the exact steps

Nothing below invents a credential. Every value is one you read out of your own
project, and none of them belongs in the repository.

1. **Create the project** at supabase.com. Any region; it hosts Auth only in
   this deployment, and may host Postgres as well if you want one vendor.
2. **Read the two public values** from *Project Settings → API*: the **Project
   URL** (`https://<ref>.supabase.co`) → `SUPABASE_URL`, and the **anon /
   publishable key** → `SUPABASE_ANON_KEY`. Both are safe in the browser bundle.
   Do **not** take the `service_role` key for either: the auth provider never
   sends it, and this deployment has no storage that needs it.
3. **Enable the sign-in method** under *Authentication → Providers*. The
   frontend implements email-and-password
   (`POST /auth/v1/token?grant_type=password`, `src/lib/session.ts`), so enable
   **Email**. If you turn on *Confirm email*, an unconfirmed account cannot sign
   in — create the first user with confirmation already completed, or disable it
   for the first deploy.
4. **Set the redirect/site URL** under *Authentication → URL Configuration* to
   the frontend origin. This build signs in through the token endpoint rather
   than a redirect flow, so it matters only if you later enable a provider that
   redirects — set it correctly now rather than debugging it then.
5. **Create the first user** in *Authentication → Users → Add user*. There is no
   self-service sign-up screen in this build.
6. **Give that user an organization.** This is the step most easily missed:
   Supabase authenticates the person, and this application decides what they can
   see. A user with no membership gets `403 "You do not belong to any
   organization yet."` — correct, and confusing if you were not expecting it.
   The first organization is created by the signed-in user themselves via
   `POST /v1/organizations`, which is the one route with no organization scope
   and makes its creator an `admin`.
7. **Configure the backend**: `AUTH_PROVIDER=supabase`, `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`. A missing one is a startup failure.
8. **Build the frontend with the same two values**, because the browser signs in
   against Supabase directly. A backend on Supabase auth plus a frontend built
   without them means nobody can sign in.
9. **Verify with a real sign-in** before believing any of it works. Until a
   person has signed in against the real project, the correct statement is that
   this path is implemented and offline-tested, not that it works.

**Identity binds on the subject.** If you delete and recreate a Supabase user
with the same email, they are a *different person* to this application and will
have no memberships — that is the M1_SECURITY_AUDIT §A-1 rule working, not a
bug.

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
AUTH_PROVIDER=supabase
SUPABASE_URL=…
# Both keys are required by AUTH_PROVIDER=supabase. The anon key verifies the
# caller's own token; the service-role key is for storage and stays server-side.
SUPABASE_ANON_KEY=…
SUPABASE_SERVICE_ROLE_KEY=…
# Shared by every instance. The app refuses to start without it in production.
MEDIA_URL_SECRET=…
# `local` is the only storage provider in this build (§4, §5). On more than one
# instance this must be a volume all of them mount.
STORAGE_PROVIDER=local
LOCAL_STORAGE_DIR=/var/lib/campaign-os/storage
LLM_PROVIDER=gemini
IMAGE_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=…
```

`tests/test_deployment_startup.py` builds `Settings` from this block and
constructs every provider it selects, so the list cannot drift back into one
that does not boot. It was previously two startup failures deep: the anon key
was missing, and `STORAGE_PROVIDER=supabase` has no adapter.

### Build time or runtime — the distinction that bites

| Variable | Where | Why it matters |
|---|---|---|
| `API_BASE_URL` | **frontend, build time** | inlined into the bundle by `next build`. Changing it needs a rebuild, not a restart |
| `SUPABASE_URL` | **both** | frontend build time *and* backend runtime. The browser signs in directly; the backend verifies the resulting token |
| `SUPABASE_ANON_KEY` | **both** | same. Publishable by design |
| everything else | **backend runtime** | read from the environment at process start |

A variable in the wrong column is the most common first-deploy failure: setting
`API_BASE_URL` on the frontend *host* rather than in its *build* leaves the
built bundle pointing wherever it was built.

### What production refuses to start on

`APP_ENV=production` rejects configuration that is valid everywhere else,
because each of these produces a deploy that comes up looking healthy:

| Refused | Reason |
|---|---|
| `AUTH_PROVIDER=dev_stub` | authenticates **every caller as the same user**. Constructed at startup so this is a boot failure, not a `500` on the first request |
| `CORS_ORIGINS=*` | with `allow_credentials=True` every browser rejects it anyway, so it fails confusingly rather than safely. Name the origin |
| `CORS_ORIGINS` empty | `curl` works and no browser can reach the API |
| `CORS_ORIGINS` over `http://` | a credentialled cross-origin call over plaintext |
| `DATABASE_URL` at localhost | the deploy never set it |
| `DEMO_MODE=true` | a demonstration instance is not a production one; it forces mock providers, so real users would be served mock output |
| missing `MEDIA_URL_SECRET` | per-process keys mean instance A cannot verify instance B's links |
| any provider with no adapter | `supabase` storage, `leonardo` images, `tavily` search |

All are asserted in `tests/test_deployment_startup.py`.

## 8. First deployment — the recommended configuration

**Real auth, real database, mock model providers.** This is the configuration to
deploy and verify first, because it exercises every path that can go wrong in
hosting — sign-in, CORS, signed media, the volume, migrations — while spending
nothing and depending on no external model API.

```bash
APP_ENV=production
DATABASE_URL=postgresql+asyncpg://…
DATABASE_URL_SYNC=postgresql://…
CORS_ORIGINS=https://app.example.com
AUTH_PROVIDER=supabase
SUPABASE_URL=…
SUPABASE_ANON_KEY=…
MEDIA_URL_SECRET=…
STORAGE_PROVIDER=local
LOCAL_STORAGE_DIR=/var/lib/campaign-os/storage
LLM_PROVIDER=mock
IMAGE_PROVIDER=mock
EMBEDDING_PROVIDER=mock
SEARCH_PROVIDER=none
```

`DEMO_MODE` stays **false**: this is a real production instance that happens to
use mock model providers, not a declared demonstration. The interface shows no
demo badge, which is correct — but be aware that generated plates are mock
output, so do not show them to anyone as model results.

**Going live on real models afterwards** is three variables and a key —
`LLM_PROVIDER`, `IMAGE_PROVIDER`, `EMBEDDING_PROVIDER` to `gemini` plus
`GEMINI_API_KEY` — and a restart. Nothing else changes, which is the point of
the provider abstraction. Do it as a second step, after the hosting itself is
proven.

## 9. Demonstration deploy

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

## 10. Deployment runbook and smoke tests

### Deploy

```bash
# 1. Database — once, before the API starts. Never from inside the API process:
#    two instances racing the same migration is the one unrecoverable case.
cd backend
DATABASE_URL_SYNC=postgresql://…  uv run alembic upgrade head
uv run alembic current            # expect: 0010_memberships_user_index (head)

# 2. Backend. --host 0.0.0.0 is what makes it reachable from outside a
#    container; API_HOST is not read by anything (§2).
uv sync --no-dev
uv run uvicorn app.main:app --host 0.0.0.0 --port "$PORT"

# 3. Frontend. API_BASE_URL is baked in here and cannot be changed later.
cd ../frontend
npm ci
API_BASE_URL=https://api.example.com \
  SUPABASE_URL=https://<ref>.supabase.co \
  SUPABASE_ANON_KEY=… \
  npm run build
npm run start
```

If the backend refuses to start, read the message: it names the variable. That
is the design — a refusal at boot is cheaper than any of the failures in §7.

### Smoke tests, in order

Stop at the first failure; each one depends on the ones above it.

**Reachability**

1. `curl https://api.example.com/v1/health` → `200`, `"status": "ok"`,
   `"database": "ok"`, and **`provider_status` all `ok`** — including `auth`.
   A `degraded` here names the seam that did not construct.
2. `provider_status.auth` is `ok` and `providers.auth` is `supabase`. If it says
   `dev_stub` the backend is not in production mode and **every caller is the
   same user** — stop and fix that before anything else.
3. Open the frontend. In the browser's network tab, confirm requests go to the
   API origin and **not** to `localhost` or `127.0.0.1`. A build with the wrong
   `API_BASE_URL` fails exactly here and nowhere earlier.
4. No CORS errors in the console. One means `CORS_ORIGINS` does not name the
   frontend origin **exactly**, scheme and host and port.

**The journey** — sign in, then open each screen and confirm it renders its own
content rather than an error or a permanent skeleton:

5. sign in · 6. `/app` · 7. organization · 8. project · 9. campaign ·
10. Discovery · 11. Inspiration · 12. Creative · 13. Generate · 14. Evaluate ·
15. Guardian · 16. Refine · 17. Compose

**Media and storage**

18. An image loads on a screen that shows one — a reference, a plate or a final
    asset. A broken image with the link present means `MEDIA_URL_SECRET` differs
    between instances, or the volume is not the one that was written to.
19. Download a final asset. This proves the volume is readable and that
    `download_url` round-trips.
20. Redeploy the backend, then reload a screen with an image. **If it 404s, the
    volume is not persistent** — the single most common hosting mistake here,
    and invisible until the first redeploy.

**Authorization** — needs a second Supabase user, added to the same organization
with role `viewer`:

21. The viewer can read every screen above.
22. A viewer mutation is refused with `403` and a message naming the capability.
    From their session: `POST /v1/projects` with any name.
23. A **non-member** — a third user with no membership — gets `403 "You do not
    belong to any organization yet."`, and a request carrying another
    organization's id gets `404`, never `403`. Existence is not leaked.

**Data**

24. If the benchmark is seeded, open a benchmark campaign's Creative screen: it
    must show three routes and the approved plan, not "No creative routes yet".
25. No critical errors in the browser console on any screen.

### What a failure at each stage means

| Fails | Almost always |
|---|---|
| 1–2 | backend environment — read the startup log, it names the variable |
| 3 | frontend built without `API_BASE_URL`, or built before it was set |
| 4 | `CORS_ORIGINS` missing the exact frontend origin |
| 5 | frontend built without `SUPABASE_URL` / `SUPABASE_ANON_KEY`, or no user exists |
| 6–17 | a user with no organization membership (§6 step 6) |
| 18–20 | storage volume: not shared, not persistent, or more than one instance |
| 21–23 | roles not assigned in `memberships` |

## 11. What this deployment cannot do

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

## 12. Upgrades

1. `alembic upgrade head` against the new code, before it starts.
2. Deploy the backend.
3. Deploy the frontend.

Migrations are additive. Nothing in this project drops a column that a running
older instance still reads, so a rolling deploy is safe; a migration that ever
needs to would have to be split across two releases.
