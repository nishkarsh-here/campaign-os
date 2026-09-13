# campaign-os

**From brainstorm to brand-ready campaign.**

An AI marketing and branding **orchestration** platform. It turns fragmented
human intent, brand knowledge, creative references and market context into
approved, multi-channel campaign assets — with humans at the decisions that
matter and a machine-checked audit trail behind every one.

```
INTENT → INTELLIGENCE → STRATEGY → APPROVAL → GENERATION → EVALUATION → REFINEMENT → FINAL ASSET
```

Not an image generator with a chat box. The image model is one replaceable step
inside a governed, resumable workflow — and it is not even the step that draws
the brand.

---

## What it actually does

A campaign walks a fixed path, and a human decides at four points along it.

**1 · Brand Brain.** Upload guidelines, datasheets, anything. They are
extracted, chunked, embedded into pgvector and read back with provenance. The
AI proposes brand facts; **only a human accepting one makes it brand truth.**
`BrandProfile` holds confirmed facts, never model output.

**2 · Campaign discovery.** A LangGraph interview asks only what it cannot
already work out — it consults the Brand Brain before asking — and terminates
on a budget. What you assert outright is recorded as `STATED`; what it infers
is `INFERRED`, and the two are never collapsed. The result is the **Campaign
Specification**: the single source of truth. A prompt never is.

**3 · Reference intelligence.** Reference images are analysed for *style*, and
the schema has no field that could hold reproducible content — no quoted text,
no logos, no coordinates, no font names (ADR-011). Learn the style, never copy
the design. Preference weights are derived on read, never supplied.

**4 · Creative Director.** Three strategic directions, checked for genuine
distinctness by deterministic set overlap rather than hoped to be different.
**Gate 1**: a human picks one. It becomes a **Creative Specification** — how to
build it. **Gate 2**: a human approves that.

**5 · Prompt Compiler.** The approved specification compiles deterministically —
no model call — into a typed `CanonicalPrompt`, then into per-provider
`ModelPrompt`s. A prompt is a build artefact, regenerable from its source, and
never the source itself. The image model is told to leave the type area quiet
and is never asked to render brand text.

**6 · Generation.** Explicit database-backed jobs per provider, with partial
success, visible failure and per-provider retry. Every asset is a
`VISUAL_PLATE` and the column records it.

**7 · Creative Evaluator.** Ten dimensions scored 0–100 against the asset's
*own* specification version. **The model scores; the code decides** — the
overall total is a weighted mean and the disposition comes from published
thresholds, and `CreativeEvaluation` validates that its own total follows from
its own dimensions. The recommendation declines to name a winner when nothing
passed.

**8 · Brand Guardian and revision.** A separate question from "how good is it?":
*is this acceptable for this brand?* Claim safety, brand restrictions and
palette are decided in code, not asked of a model, and the verdict is computed
from the checks. Feedback becomes an explicit KEEP / CHANGE / ADD / REMOVE plan
shown before anything runs. Approving produces a new specification version;
**the previous one stays byte-for-byte intact** and the assets made from it keep
pointing at it.

**9 · Final composition.** The plate becomes a deliverable: deterministic Pillow
composition of logo, headline, call to action, exact brand colours and safe
areas. **The `LayoutSpec` is the source of truth and the PNG is its output**
(ADR-014) — editing changes data and re-renders. A constrained editor refuses
rather than silently dropping a change; channel variants are re-layouts, not
regenerations; every edit is a new version and nothing is overwritten.

**10 · Per-channel copy.** A campaign is one plan expressed differently per
channel, not one plan resized. A channel may carry its own headline, subhead and
call to action; an absent override inherits the campaign's. Overrides are
approved at the same human gate as the rest of the plan, restricted to the
channels the Campaign Specification declares, scanned by the Brand Guardian, and
revisable one channel at a time — and the composition editor still refuses to
rewrite them, now against that channel's own approved words.

## Why the architecture looks like this

Eight rules, each of which cost something to hold:

1. **The Campaign Specification is the source of truth, never a prompt string.**
2. **No provider-specific code outside `app/providers/`.** Five `typing.Protocol`
   interfaces; adapters match rather than inherit.
3. **Everything the graph passes around is typed.** Pydantic in `app/domain/`.
4. **Every node declares its contract**, and a test fails the build if a node
   writes a key it did not declare.
5. **Mock providers are first-class.** The entire product runs end to end with
   no network and no key, forever.
6. **Deterministic software owns typography and layout** (ADR-006).
7. **Explicit job status, always.** Failures are recorded, never swallowed.
8. **Never expose chain-of-thought.** One short user-facing rationale, and that
   is the only reasoning surface.

Where a decision was contested it is written down as an ADR in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — including the three places
where the M0 design was wrong and the build corrected it (generation, revision
and final composition all left the graph, for reasons recorded in ADR-012,
ADR-013 and ADR-014).

## Status

**Milestones 0–11 complete.** Nothing here claims to work that does not.

| | |
|---|---|
| Tests | 1,107 passing · ruff clean · mypy strict clean · tsc clean · Next build clean |
| Migrations | 001–009, `alembic check` clean |
| API | 62 routes under `/v1` |
| Frontend | 13 routes, all four async states on every screen |
| Providers | mock (complete) · Gemini (LLM, image, embedding) · Leonardo (image) · local + Supabase storage |
| Graph | LangGraph with a Postgres checkpointer, resume proved across two processes |

**Honest limitations** are in [§9 of the deployment guide](docs/DEPLOYMENT.md#9-what-this-deployment-cannot-do)
and in `M10_FINAL_REPORT.md`. The short version: background work runs in the API
process and does not survive a restart (it is reconciled into a visible failure
at startup); local storage does not work behind more than one instance; the
renderer falls back to a bundled typeface when a brand has not uploaded one; and
**live Gemini generation is unverified — the credential available in this
environment is rejected by the provider.** Mock mode is the guaranteed path.

## Quick start

Requires PostgreSQL 16+ with `pgcrypto`, `citext` and `vector` available. No
Docker, no cloud account, no API key.

```bash
createdb campaign_os && createdb campaign_os_test
cd backend && cp ../.env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run pytest
uv run uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000/app>.

## Demo mode

```bash
# backend/.env
DEMO_MODE=true
LLM_PROVIDER=mock
IMAGE_PROVIDER=mock
EMBEDDING_PROVIDER=mock
```

```bash
cd backend && uv run python scripts/seed_demo.py --reset
```

That builds the canonical demo campaign **by running the real services** — the
interview really runs, the evaluator really scores, the revision really produces
v2, the renderer really composes. Nothing is written into a table that a service
is supposed to compute. It prints the campaign URL when it finishes.

`DEMO_MODE=true` refuses to start against a non-mock provider, so a
demonstration cannot come to depend on a network that may not be there. The
badge in the header says so out loud.

The walkthrough is scripted in [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

## Production

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). In short: run migrations, run
the API with `AUTH_PROVIDER=supabase` and `APP_ENV=production` (the dev auth
stub refuses to construct in production), point `STORAGE_PROVIDER` at a bucket
if you run more than one instance, and give the frontend `API_BASE_URL`.

## Read in this order

1. [`CLAUDE.md`](CLAUDE.md) — the working rules for this repository
2. [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — what we are building and why
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system shape and 14 ADRs
4. [`docs/GRAPH_SPEC.md`](docs/GRAPH_SPEC.md) — the LangGraph contract, and where the plan changed
5. [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) · [`docs/API_SPEC.md`](docs/API_SPEC.md) · [`docs/UI_SPEC.md`](docs/UI_SPEC.md)
6. [`docs/TESTING.md`](docs/TESTING.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) · [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Stack

Next.js · TypeScript · Tailwind · FastAPI · LangGraph · PostgreSQL + pgvector ·
SQLAlchemy 2 · Pydantic v2 · Pillow · Gemini · uv

> **Do not move this repository under `~/Desktop` or `~/Documents`.** Those are
> iCloud-synced; syncing a venv and `node_modules` makes a single Python import
> take minutes. See the environment note in `CLAUDE.md`.
