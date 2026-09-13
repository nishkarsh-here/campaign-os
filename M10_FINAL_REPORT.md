# M10_FINAL_REPORT.md

Milestone 10 — production polish, reliability, deployment and demo hardening.
The build is complete; the architecture is frozen.

---

## 1. Product status

`campaign-os` turns messy human marketing intent into approved, brand-safe,
multi-channel campaign assets, with a human decision at every point where one
matters and a machine-checked trail behind each one.

```
INTENT → INTELLIGENCE → STRATEGY → APPROVAL → GENERATION → EVALUATION → REFINEMENT → FINAL ASSET
```

Every stage is implemented and reachable from the product. Nothing is stubbed
and described as working.

| | |
|---|---|
| Automated tests | **1,067 passing**, 0 failing |
| Lint / format | ruff clean, 164 files formatted |
| Types | mypy `--strict` clean across 109 modules; TypeScript clean |
| Frontend build | Next production build clean, 13 routes |
| Migrations | 001–009 applied; `alembic check` reports no drift |
| API | 62 routes under `/v1` |
| Demo | one canonical campaign, seeded end to end in ~15 seconds, offline |

## 2. Features complete

**Brand Brain (M2).** Brand CRUD; document upload validated by magic bytes;
PDF and text ingest → chunk → embed → pgvector; scoped retrieval with
provenance. AI-extracted facts stay **proposals** until a human accepts them —
model output never becomes brand truth on its own.

**Campaign discovery (M3).** A LangGraph interview that consults the Brand
Brain before it asks, prioritises by impact, and terminates on a budget.
Stated and inferred are tracked per field and never collapsed. The **Campaign
Specification** is the single source of truth; human edits are marked and
survive recompilation.

**Reference intelligence (M4).** References analysed for style through the
multimodal provider abstraction, into a schema with no field that could hold
reproducible content. Preference weights are derived on read, never supplied.

**Creative Director (M5).** Three directions, checked distinct by deterministic
set overlap. Two human gates on real interrupt/resume. Confirmed campaign facts
are pinned after both model calls rather than requested from the model.

**Prompt Compiler (M6).** Deterministic compilation — no model call — from the
approved specification to a typed `CanonicalPrompt` and per-provider
`ModelPrompt`s. Typography reaches an image model only as "leave this area
quiet". Every generated asset is a `VISUAL_PLATE`.

**Generation (M6).** Database-backed jobs per provider; partial success is
success and says so; failures carry a reason and a retry.

**Creative Evaluator (M7).** Ten dimensions scored against the asset's *own*
specification version. The model scores; the code computes the total from
published weights and the disposition from published thresholds. Ranking is
derived with total ordering. The recommendation declines when nothing passed.

**Brand Guardian and revision (M8).** A separate question from quality, with
claim safety, brand restrictions and palette decided in code. The verdict is
computed from the checks; a failed check is never an implicit pass. Feedback
becomes an explicit KEEP/CHANGE/ADD/REMOVE plan shown before anything runs.
Applying it is a pure function, and the previous version stays byte-for-byte
intact.

**Final composition (M9).** Deterministic Pillow composition of logo, headline,
call to action, exact brand colours and safe areas. The `LayoutSpec` is the
source of truth and the PNG is its output. A constrained editor that refuses
with a sentence rather than silently dropping a change. Channel variants as
re-layouts. PNG and JPEG export with full provenance, nothing overwritten.

**New in M10.**

- **Demo mode** — a declaration, not a coincidence. `DEMO_MODE=true` refuses to
  start against any non-mock provider, is reported on `/v1/health`, and shows as
  a badge in the header.
- **Seed script** (`scripts/seed_demo.py`) — builds the canonical campaign by
  running the real services, resettable, idempotent, and refuses to run against
  a live provider.
- **Campaign command centre** — `GET /v1/campaigns/{id}/overview` and
  `/app/campaigns/{id}/overview`. A read model composed from the services that
  own each stage; it stores nothing and derives nothing.
- **Startup reconciliation** — a restart mid-job becomes a visible, retryable
  failure instead of a permanent spinner.
- **Provider-secret redaction** — key-shaped strings are stripped from vendor
  error detail before it can reach a log line.
- **Gemini smoke test** (`scripts/gemini_smoke_test.py`) — the only thing in the
  repository that reaches an external service, run deliberately and by hand.

## 3. Demo mode instructions

```bash
# backend/.env
DEMO_MODE=true
LLM_PROVIDER=mock
IMAGE_PROVIDER=mock
EMBEDDING_PROVIDER=mock
MOCK_FAILURE_MODE=none
```

```bash
cd backend
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset      # ~15s, prints the campaign URL
uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

The seed produces: one organization, one project, one brand with a palette,
prohibited claims, a logo and an ingested guidelines document (10 accepted
facts), one campaign through a real interview plus human edits, three analysed
references with preferences, three creative directions through both gates,
three generated plates, three evaluations and a selection, three brand checks,
**one full revision round to v2**, three more plates, six evaluations, six brand
checks, and three final branded assets across Instagram post, Instagram story
and LinkedIn.

`--reset` deletes only what the seed created. `--drop` deletes without
rebuilding. Running it plain is a no-op when the data is already there.

The presentation walkthrough is scripted in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## 4. Production mode instructions

```bash
APP_ENV=production
AUTH_PROVIDER=supabase          # dev_stub REFUSES to construct in production
STORAGE_PROVIDER=supabase       # local storage does not work behind >1 instance
LLM_PROVIDER=gemini
IMAGE_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=…
DEMO_MODE=false
```

Selecting a provider without its credential fails **at startup**, not at the
first user request. So does an embedding provider whose vector width disagrees
with the column.

## 5. Deployment instructions

Full guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). In short — two processes
and a database, no broker, no Docker required:

1. PostgreSQL 16+ with `pgcrypto`, `citext`, `vector`.
2. `uv run alembic upgrade head` **before** the new API starts.
3. `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (set `API_HOST=0.0.0.0`;
   the `127.0.0.1` default is the most common reason a first deploy answers
   nothing).
4. Frontend built with `API_BASE_URL` set to an origin the **browser** can reach.
5. `CORS_ORIGINS` set to the frontend origin.

`GET /v1/health` returns `200` with `"status": "degraded"` when the database is
unreachable, so a platform health check distinguishes "process up, database
down" from "process gone".

## 6. Environment variables

`.env.example` is the complete list, marked `[required]`, `[optional]`,
`[development]`, `[demo]` and `[provider]`. It is **asserted against `Settings`
in both directions** by `tests/test_config.py`: an undocumented setting fails,
and so does a documented knob nothing reads.

That test found a real defect. `LANGGRAPH_STRICT_MSGPACK=true` had sat in the
example for several milestones looking like a security control. Nothing read it
— the allowlist is applied unconditionally in `build_serde()`, and
pydantic-settings loads `.env` into `Settings`, never into `os.environ`. It has
been removed and replaced with a note saying why there is no knob.

**No secret reaches the browser.** There is no `NEXT_PUBLIC_*` variable in this
project and none should be added: the frontend has no secrets because it talks
to nothing but our API.

## 7. Test results

```
pytest        1,067 passed
ruff check    All checks passed
ruff format   164 files already formatted
mypy --strict Success: no issues found in 109 source files
tsc           clean
next build    Compiled successfully, 13 routes
alembic check No new upgrade operations detected
```

M10 added 22 tests. None was added to raise a count; each covers something that
was found or changed:

| Area | What it asserts |
|---|---|
| Command centre (9) | every stage present and explained; an unstarted stage never reads as finished; the overview **agrees with the service it summarises**; tenancy at both service and HTTP layers |
| Restart recovery (5) | an abandoned job becomes a visible retryable failure; a job inside the grace window is **not** killed; terminal rows are never rewritten; reconciliation is idempotent |
| Secret redaction (4) | key-shaped strings never survive into `detail`; ordinary messages are left alone (over-redaction is its own failure); the user-facing message is untouched |
| Environment contract (2) | `.env.example` and `Settings` agree both ways |
| Storage URL contract (1, rewritten) | `signed_url` returns something deliberately **not** fetchable |

### Live verification

| Checked | Result |
|---|---|
| Full demo path, seeded end to end | ✅ all 24 script steps produce real output |
| Command centre against the seeded campaign | ✅ six stages DONE, spec v2, Guardian PASS, 1 revision, 3 channels, 6 ranked assets |
| Every route returns 200 | ✅ 8 campaign routes + 3 workspace routes |
| Compose → edit → re-render | ✅ layout v1→v2 while the asset stayed v1 until re-rendered, then v2 |
| Browser refresh mid-composition | ✅ layout v2, asset v2, 4 exports — unchanged |
| Backend restart, campaign state | ✅ identical overview before and after |
| **Backend restart mid-interview** | ✅ a fresh process resumed at turn 2 on the same pending question (`key_message`) |
| Deliberate invalid layout edit | ✅ `400 VALIDATION_FAILED`, "That position would put the element outside the canvas", no version written |
| Rewriting an approved CTA | ✅ `400`, names the approved value, no version written |
| Malformed ids, traversal attempts | ✅ all `404`, no stack traces |
| Bad payloads | ✅ all `400` with a field and a request id |

## 8. Security results

Targeted review against the boundaries this product actually has. Three real
findings, all fixed.

| Area | Finding |
|---|---|
| Authentication boundary | ✅ `DevStubAuthProvider` raises at construction under `APP_ENV=production`. Identity binds on the IdP subject, never the email. |
| Organization isolation | ✅ enforced in the repository layer, with a parametrized cross-tenant probe over **every** scoped repository and a guard test that fails if a new one is not registered. Cross-tenant reads are `404`, never `403`. |
| Campaign / brand / asset isolation | ✅ every byte-serving route resolves a scope-checked row before reading its storage key. An asset id from one campaign is `404` under another's URL. |
| **Storage addressing** | 🔧 **Fixed.** `LocalStorageProvider.signed_url` returned `/v1/files/{key}` — a route that was specified in M0, never built, and should not be: a key in a URL is an object address with no organization attached. It now returns a deliberately unfetchable `local://` reference, the API spec records why the route does not exist, and the test asserts the new contract. |
| **Dead configuration** | 🔧 **Fixed.** `PUBLIC_ASSET_BASE_URL` advertised a public asset base that nothing used and no route served. Removed. |
| **Secrets in logs** | 🔧 **Fixed.** Vendor exceptions quote the request that produced them, and a provider authenticating by query parameter puts the key in that request. `ProviderError.__init__` now redacts key-shaped strings by pattern — the one place every adapter's detail passes through. Pattern-based rather than value-based, because a rule that only redacts the keys we remembered to pass in fails on the one we forgot. |
| Path traversal | ✅ storage keys are pattern-validated, `..` rejected, and the resolved path is confirmed inside the root before any filesystem access. Probes return `404`. |
| Unsafe filenames | ✅ no storage key is derived from user input. Every one is generated with an organization and campaign prefix plus a UUID. |
| API input validation | ✅ Pydantic at every boundary with `extra="forbid"`. Malformed ids `404`; bad payloads `400` with a field and a request id. |
| Error leakage | ✅ no handler returns an internal message or a stack. Provider detail stays log-side; the client gets a usable sentence and a request id. |
| Browser/server boundary | ✅ no `NEXT_PUBLIC_*` variable, no credential in the bundle, no direct storage access from the browser. |

## 9. Known limitations

Stated plainly. A limitation you know about is a trade; one you discover is an
outage.

1. **Background work does not survive a restart.** Generation, evaluation and
   brand checks are in-process `asyncio` tasks (ADR-012). At startup the API
   marks anything a previous process abandoned as `FAILED` with "interrupted by
   a server restart", so it is visible and retryable rather than a spinner that
   never resolves. A wrong-but-honest failure beats a permanent spinner.
2. **That reconciliation is a heuristic across instances.** It only touches rows
   older than the generation timeout plus five minutes. With one instance it is
   exact; with several it is very nearly exact. Making it a guarantee needs
   leases and a coordinator — the worker architecture this product deliberately
   does not have.
3. **Local storage does not work behind more than one instance.** Use Supabase
   storage or a shared volume.
4. **No rate limiting.** Provider spend is bounded by the per-batch image count
   and the timeouts, not by request volume. Put a limit at the edge before
   exposing this publicly.
5. **Typography falls back.** The renderer uses a brand-uploaded TrueType face
   when one exists and Pillow's bundled face otherwise. It does not identify,
   download or substitute a named typeface. A brand whose guidelines specify a
   licensed face gets a render correct in layout but not in typeface.
6. **Print is refused, not supported.** The layout engine can size an A3 canvas;
   print *production* — CMYK, bleed, crop marks, PDF — is not built, and the API
   refuses a print channel with a reason.
7. **Long-running jobs have no progress detail.** `PENDING`, `RUNNING`, or
   terminal. There is nothing underneath that could honestly produce a
   percentage.
8. **Switching embedding provider invalidates stored vectors.** They were
   produced by a different model. Re-ingest, or keep the provider fixed.
9. **The dev auth stub has no real authentication.** It is guarded against
   production and is not a security model.
10. **`/v1/docs` is served in every environment.** It documents the API, not the
    data; disable it at the edge if you would rather not publish the shape.

## 10. Gemini live status

> **Live Gemini image generation is NOT verified. The credential available in
> this environment is rejected by the provider.**

One controlled smoke test was run, deliberately and by hand, through
`scripts/gemini_smoke_test.py` — the only code in this repository that reaches
an external service:

```
  config       model gemini-2.5-flash-image, key ending …usDg
  gemini       requesting one image…
FAILED — Gemini refused the request: The image service rejected this
         workspace's credentials.
```

The failure is at the **credential**, not in our adapter: the request was built,
sent and rejected with an authentication error, which is the provider's answer
rather than ours. The adapter itself is covered by unit tests that drive it with
a fake SDK client (success, timeout, rate limit, blocked content, malformed
response, unconfigured key), and it maps every vendor exception to a typed
`ProviderError` with a user-safe message.

Nothing has been fabricated to paper over this. **Mock mode is the guaranteed
demonstration path, by design** — that is why the mock providers are first-class
and why `DEMO_MODE` refuses to depend on a network.

To verify when a working key is available:

```bash
cd backend && GEMINI_API_KEY=… uv run python scripts/gemini_smoke_test.py
```

It exits `0` only after a real image has been generated, decoded and
round-tripped through storage.

## 11. Demo script

Full script with narration: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).
Twenty minutes, entirely offline. The spine:

1. **Command centre** — the whole campaign in one screen.
2. **Brand Brain** — accepted facts, palette, prohibited claims.
3. **Campaign Specification** — stated vs inferred, a human edit marked "Yours".
4. **References** — style analysed, weights derived.
5. **Creative Director** — three distinct directions, **Gate 1**.
6. **Creative Specification** — **Gate 2**, pinned campaign facts.
7. **Compiled prompt** — deterministic, and carrying no brand text.
8. **Generation** — three plates, all labelled `VISUAL_PLATE`.
9. **Evaluation** — six ranked, three dispositions, a ten-dimension matrix; the
   model scored, the code decided.
10. **Brand Guardian** — a real failed tone check with the verdict computed.
11. **Revision** — the KEEP/CHANGE plan, v2 approved, **v1 untouched**.
12. **Composition** — edit, re-render, and the **deliberate refusal**.
13. **Channel variants and export** — three channels, full provenance, download.

## 12. Future roadmap

Deliberately not built. Each would be a new milestone, not a patch.

**Near term**
- A real worker (Celery, arq, or a platform queue) so background work survives a
  restart and the reconciliation heuristic can become a guarantee.
- Supabase Auth wired into the existing `AuthProvider` seam; multi-user
  organizations with roles that actually differ.
- Rate limiting and per-organization spend caps.
- SSE or websockets to replace polling — the polling contract exists because
  polling cannot silently die, and that trade should be made deliberately.

**Product**
- Print production: CMYK, bleed, crop marks, PDF export.
- More channel sizes and per-channel copy variants.
- Campaign templates and brand-level layout presets.
- A second image provider promoted past the adapter stub.

**Explicitly out of scope** and expected to stay there: social publishing, CRM,
campaign analytics, ad buying, video generation, advanced personalization,
autonomous unlimited regeneration, real-time collaboration, and a Canva
replacement. The editor is constrained on purpose (ADR-014); widening it is how
this product would stop being an orchestration platform.

---

## Architecture freeze

Frozen from here. These do not change without a genuine correctness reason;
everything else is a roadmap item.

- The **Campaign Specification** as the source of truth
- The **Creative Specification** as the execution source
- **`LayoutSpec`** as the composition source
- The **LangGraph** workflow architecture and its Postgres checkpointer
- The five **provider Protocols**
- **Organization-scoped repositories** as the tenancy mechanism
- **Versioned artifacts** — never mutation
- The **human approval model** — four gates, each a real decision
