# CLAUDE.md — working rules for this repository

> Read this before touching anything. It is the operating manual for the repo,
> not a description of the product. For the product, read `docs/PRODUCT_SPEC.md`.

## 1. What this repo is

`campaign-os` — an AI marketing & branding **orchestration** platform.
It turns messy human marketing intent into approved, brand-safe, multi-channel
campaign assets:

```
INTENT -> INTELLIGENCE -> STRATEGY -> APPROVAL -> GENERATION -> EVALUATION -> REFINEMENT -> FINAL ASSET
```

It is **not** an image generator with a chat box in front of it. The image model
is one replaceable step inside a governed workflow.

`campaign-os` is a working codename. The product name is not decided; changing it
means editing `PRODUCT_NAME` in `backend/app/config.py` plus the docs headings.

## 2. Project isolation (hard rule)

This project shares no code, schema, prompt, config or convention with any other
project on this machine. Do not read other project folders for "reference", do not
copy patterns from them, do not import a dependency because another project used it.
The files in this repository plus `docs/` are the only source of truth.

Note: `$HOME` is itself a git repository belonging to unrelated coursework.
This repo has its own `.git` at the project root and must stay that way.

## 3. Non-negotiable architectural rules

1. **The Campaign Specification is the source of truth, never a prompt string.**
   Human conversation -> structured campaign data -> `CampaignBrief` ->
   `CreativeSpecification` -> model-specific prompt. Prompts are a *rendering* of
   structure, produced at the last possible moment, and are always regenerable.
2. **No provider-specific code outside `app/providers/`.** Nodes, services and
   routes talk to `LLMProvider`, `ImageProvider`, `EmbeddingProvider`,
   `StorageProvider`, `SearchProvider`. If you are writing `google.genai` or
   `leonardo` anywhere else, you are doing it wrong.
3. **Everything the graph passes around is typed.** Pydantic models in
   `app/domain/`. No bare `dict[str, Any]` for domain data. `dict` is acceptable
   only for a node's *partial state update* return value, which is validated
   against `CampaignState` on merge.
4. **Every node declares its contract.** A node in `app/graph/nodes/` must have a
   `NodeContract` in `app/graph/contracts.py` naming what it reads and writes.
   `tests/test_node_contracts.py` fails the build if a node writes a key it did
   not declare. This is how "defined inputs and outputs" is enforced mechanically
   rather than by good intentions.
5. **Mock providers are first-class.** The full end-to-end flow must run with
   `LLM_PROVIDER=mock IMAGE_PROVIDER=mock` and no network access, forever. Every
   test suite runs this way. This is a graded, demoed project — a dead API key
   must never be able to break the demo.
6. **Deterministic software owns typography and layout.** AI generates the visual
   plate; Pillow composes logo, headline, CTA, colours, safe areas and exports.
   Do not ask an image model to render brand text. See ADR-006.
7. **Explicit job status, always.** `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`.
   No operation may leave a row in an unknown state. Failures are recorded, not swallowed.
8. **Never expose chain-of-thought.** Nodes emit a short `rationale` /
   `decision_summary` field intended for users. That is the only reasoning surface.

## 4. Repository layout

```
docs/                 architecture + specs (read before large changes)
backend/
  app/
    config.py         settings, single source of env truth
    domain/           Pydantic domain schemas  <- the contracts
    graph/
      state.py        canonical CampaignState
      contracts.py    NodeContract registry
      nodes/          one file per node (Milestone 4+)
    providers/
      base.py         Protocol interfaces
      registry.py     env -> concrete provider
      mock/ gemini/ leonardo/ local/
    services/         orchestration + persistence (Milestone 1+)
    repositories/     DB access, one per aggregate (Milestone 1+)
    api/              FastAPI routers (Milestone 1+)
  migrations/         Alembic (Milestone 1+)
  tests/              unit / integration / e2e
frontend/             Next.js App Router (Milestone 1+)
```

## 5. How to work here

- **Build vertically.** A thin working path from brand to final asset beats ten
  polished modules that do not connect. See `docs/ROADMAP.md`.
- **Inspect before you modify.** Read how a module is used before changing it.
  Preserve API contracts unless the change is deliberate and documented.
- **One responsibility per file.** If a file needs "and" to describe it, split it.
- **Tests are part of the change, not a follow-up.** Meaningful logic ships with
  tests. Run them before you say a thing works.
- **Document decisions.** Anything architectural goes in `docs/ARCHITECTURE.md`
  as an ADR. Any schema change goes in `docs/DATABASE_SCHEMA.md` plus a migration.
- **Never claim a feature works because code exists for it.** See the Definition
  of Done below. If something is stubbed, the docs and the response must say so.
- **Do not delete working code to make an error disappear.** Understand the cause.

## 6. Commands

```bash
# backend (uv-managed, Python 3.13)
cd backend
uv sync                       # install/refresh the environment
uv run pytest                 # full test suite (mock providers, no network)
uv run pytest -m unit         # fast unit tests only
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run uvicorn app.main:app --reload --port 8000      # Milestone 1+

# frontend (Milestone 1+)
cd frontend && npm run dev
```

## 7. Definition of Done

A feature is done when **all** of these hold. Code existing is not one of them.

- [ ] implementation exists and is reachable from the product, not just importable
- [ ] types/schemas are correct and validated at boundaries
- [ ] unit tests for the logic, integration test for the seam it crosses
- [ ] `uv run pytest` passes
- [ ] error, loading and empty states handled (API *and* UI where relevant)
- [ ] job/run status transitions are explicit and persisted
- [ ] docs updated (`ARCHITECTURE.md` / `API_SPEC.md` / `DATABASE_SCHEMA.md`)
- [ ] the mock-provider path still works end to end
- [ ] no regression in existing functionality

## 8. Security

- Secrets come from the environment via `app/config.py`. Never hardcode, never log.
- `SUPABASE_SERVICE_ROLE_KEY` and every API key are server-side only. Nothing
  secret crosses into the browser bundle. The frontend talks only to our API.
- Validate file type, magic bytes and size on every upload; validate all API input
  with Pydantic; never build SQL by string concatenation.
- Organization and project scope is checked in the repository layer, on every read
  and every write — not only in the route handler.

## 9. Current status

**Milestone 11 complete** — per-channel creative copy. Rules it established:

- **A campaign is one plan expressed differently per channel**, not one plan
  resized. `CreativeSpecification.channel_copy` is an optional
  `Channel -> {headline?, subhead?, cta?}` map; an absent override inherits, so
  every specification written before M11 resolves byte-identically.
- **One resolver, `copy_for(specification, channel)`.** The layout builder, the
  channel adapter, the composition guard and the Brand Guardian all ask it.
  Four independent `or` chains is how they come to disagree about what the
  approved words are.
- **An override is a sparse diff, not a second plan.** `ChannelCopy` uses
  `None` for "inherit"; `ResolvedCopy` is the complete answer. Collapsing the
  two types would make "not overridden" and "no headline" the same value.
- **Overrides are approved copy or nothing.** They go through Gate 2 like every
  other field, may only name channels the *Campaign Specification* declares
  (checked at the service boundary, since the Creative Specification cannot
  answer that for itself), and are refused in the composition editor.
- **A per-channel call to action is locked like the default one.** `locked_leaf`
  matches on the last path segment, so `channel_copy.linkedin.cta` cannot walk
  past the lock that `cta` would hit.
- **The Guardian scans overrides too.** They are approved copy that reaches a
  deliverable; scanning only the defaults would let a prohibited claim ship
  through the one channel nobody looked at.
- **A revision changes one channel at a time**, addressed by a dotted field
  name. The whole map cannot be revised as prose — a structured field is
  changed by the service that owns it.
- **A variant never invents an element.** A channel adapter moves what is
  there; an override cannot bring back a subhead the frame dropped.

**The freeze held.** One optional field on a frozen model, no migration, no
graph change, no new artifact. `LayoutSpec` is still the composition source and
the Campaign Specification is still the source of truth.

Previously: **Milestone 10 complete — the architecture is frozen.** Production polish,
reliability, deployment and demo hardening. Rules it established:

- **Demo mode is a declaration, not a coincidence.** `DEMO_MODE=true` refuses to
  start against any non-mock provider, so a demonstration cannot come to depend
  on a network that may not be there. It is reported on `/v1/health` and shown
  as a badge, because "is this real output?" is the first question anyone
  watching has and guessing is worse than either answer.
- **The demo dataset is built by running the real services.** `scripts/seed_demo.py`
  drives discovery, the Creative Director, both gates, generation, evaluation,
  the Guardian, a full revision round and composition. Nothing is written into a
  table a service is supposed to compute — a seeded "evaluation" nobody computed
  is the fake functionality this project has refused to build since M0.
- **The command centre is a read model.** `app/services/overview.py` composes
  the other services and stores nothing. A dashboard that derives its own
  version of "is this approved?" becomes a second source of truth, and the first
  time the two disagree the dashboard is the one people believe.
- **A restart mid-job becomes a visible failure, not a spinner.** In-process
  background work cannot survive a restart (ADR-012), so startup marks anything
  a previous process abandoned as `FAILED` with a reason. Only rows older than
  the timeout plus a grace window, so another instance's live work is never
  killed. A wrong-but-honest failure beats a permanent spinner.
- **Secrets are redacted where vendor strings become log detail.** In
  `ProviderError.__init__`, by shape rather than by value — the one place every
  adapter's detail passes through, and a rule that only redacts the keys we
  remembered to pass in is a rule that fails on the one we forgot.
- **No route ever takes a storage key from a request.** Every byte-serving
  endpoint resolves a scope-checked row and reads *its* key. The
  `/v1/files/{storage_key}` route in the M0 API sketch was never built and must
  not be.
- **`.env.example` is asserted against `Settings`, both directions.** A setting
  nobody documented is one operators cannot find; a documented knob nothing
  reads is worse. `LANGGRAPH_STRICT_MSGPACK` sat in the example for several
  milestones looking like a security control while nothing read it.

**Frozen from here.** The Campaign Specification as source of truth, the
Creative Specification as execution source, `LayoutSpec` as composition source,
the LangGraph workflow, the provider Protocols, organization-scoped
repositories, versioned artifacts and the human approval model do not change
without a genuine correctness reason. Everything else is a roadmap item.

Previously: **Milestone 9 complete and verified** — final brand composition, the
constrained editor, channel variants and export. Rules it established:

- **The `LayoutSpec` is the source of truth; the PNG is its output** (ADR-014).
  Editing changes fields on the layout and re-renders. Nothing in the system
  edits an image, because an image cannot be reasoned about — you cannot ask a
  pixel whether it clears the safe area.
- **Versions, never mutation.** An accepted edit writes a new `layout_specs`
  row; a render writes a new `final_assets` row carrying `layout_snapshot`
  inline. The id says which document it came from, the snapshot says what it
  actually rendered. An asset that has gone to a client stays what it was.
- **Geometry is checked before a pixel is drawn.** `validate_layout` returns
  blocking issues and warnings in the user's own words. A broken layout is
  reported, never rendered. The safe area governs *content* — a scrim band is
  meant to be full-bleed, and a default that warns about itself teaches people
  to ignore the panel.
- **The editor refuses; it never trims.** `EDITABLE_ELEMENT_FIELDS` is short and
  per-element-type. The CTA and legal line carry approved facts, the logo cannot
  be hidden, and every rejection is a typed `ValidationFailed` with a sentence.
  A silently dropped edit reads as an applied one, which is the worst outcome.
- **Nothing is invented.** No placeholder logo, no invented CTA, no unapproved
  colour. A brand with no logo gets a layout with no logo element.
- **Typography has a documented limitation.** A brand-uploaded TrueType face is
  used when one exists, Pillow's bundled face otherwise. No typeface is
  identified, downloaded or substituted by name.
- **Channel variants reuse `CHANNEL_DIMENSIONS`.** A variant is a re-layout, not
  a regeneration: same plate, same approved words, same logo. No model is
  called, and no second dimension table exists.
- **Composition is a product service, not a graph stage** (ADR-014). Millisecond
  deterministic work with no model call and nothing to poll. The campaign graph
  was not touched.
- **Print is out of scope and says so.** `COMPOSABLE_CHANNELS` is the five
  screen channels; composing a print size is refused with a reason. PNG and
  JPEG only — no PDF, no A3/A4 production.

Previously: **Milestone 8 complete and verified** — the Brand Guardian and the
revision loop. Rules it established:

- **Guardian and Evaluator are different questions and different modules.**
  `app/domain/guardian.py` answers "is this acceptable for this brand?";
  `app/domain/evaluation.py` answers "how good is it?". Do not merge them: a
  beautiful creative implying a prohibited claim must fail, and a merely
  adequate on-brand one must pass.
- **The verdict is computed from the checks.** `decide_verdict` turns findings
  into PASS / NEEDS_REVISION / REJECT, and `BrandGuardianResult` validates that
  its verdict follows from its own checks. A model never returns a verdict.
- **A failed check is never an implicit pass.** No checks means `UNKNOWN`, and
  a failed row leaves `verdict` null.
- **The guardian invents no rules.** Every check maps to something the Brand
  Brain defines; a brand with no palette gets `NOT_APPLICABLE`.
- **Feedback refines, never restarts.** The planner returns a *delta*, never a
  rewritten specification. `LOCKED_FIELDS` (cta, product/brand integration,
  negative constraints) can only change when the user's own words asked —
  `explicit_unlocks` is computed in code from the feedback, so a model cannot
  grant itself permission.
- **Applying a revision is a pure function** (`revision_application.py`):
  v1 + delta = exactly this v2, asserted field by field. KEEP is verified
  against the real before/after, not trusted.
- **Versions are never mutated.** v2 is a new row; v1 keeps saying what it
  said, and the assets generated from it keep pointing at it. An asset is
  always evaluated and brand-checked against *its own* version.
- **Revision gates are rows, not graph interrupts** (ADR-013). There is no
  running execution to pause.
- **Regeneration is not reimplemented.** An approved revision goes through the
  existing `GenerationService` and `EvaluationService`.

Previously: **Milestone 7 complete and verified** — the Creative Evaluator and
the recommendation engine. Rules it established:

- **The model scores; the code decides.** `ProposedEvaluation` has no overall
  score and no disposition — there is nothing there for a model to invent.
  `aggregate_score` and `decide_disposition` are pure functions of the dimension
  scores, the published weights and the thresholds, and `CreativeEvaluation`
  *validates* that its total follows from its own dimensions. Do not add a path
  that lets a caller supply either.
- **Never ask a model what the database knows.** Asset existence, MIME type,
  dimensions, campaign ownership, the source specification version — all
  checked in code (`check_evaluable`). The model is asked only for qualitative
  visual judgement.
- **An asset is judged against its own plan.** The specification is looked up by
  the version the *asset* was generated from, never the latest. After a
  Milestone 5 revision, "latest" is a plan the asset never saw.
- **The evaluator assesses; it never creates.** It may say keep, revise or
  reject. It never rewrites a prompt or a specification — that is Milestone 8.
- **Thresholds are published and tested.** `DispositionThresholds` lives in one
  place with the reasons it produces. A disposition a user cannot interrogate is
  indistinguishable from a guess.
- **Ranking is derived, never stored** — and its ordering is *total*: score,
  brand alignment, campaign fit, then asset id, so the same evaluations always
  render in the same sequence.
- **The recommendation may decline.** When every asset was rejected it says so
  rather than putting the least bad one forward; a system that always names a
  winner teaches people to ignore it. A human may select against it regardless.
- **A failed batch must not look like an empty one.** `EvaluationView` returns
  every row including failures, with a reason and a retry.
- **Concurrency gets its own session** (ADR-012), same as generation.

Previously: **Milestone 6 complete and verified** — the Prompt Compiler and
multi-model image generation. Rules it established:

- **A prompt is a build artefact, never a source of truth.** The chain is
  Campaign Specification → Creative Direction → Creative Specification →
  `CanonicalPrompt` → `ModelPrompt` → `GeneratedAsset`, and it only flows
  downhill. `PromptCompiler` reads the approved specification and never writes
  it; a provider that wants different wording gets a different `ModelPrompt`.
- **Compilation is deterministic — no model call.** The approved specification
  is already structured, so rearranging it into image controls is a pure
  function. That is what makes a prompt reproducible from its source, and it
  keeps `source_fingerprint` meaningful. Do not put an LLM in this path.
- **The image model never renders brand text** (ADR-006). Typography reaches a
  prompt only as `text_safe_area` — "leave this area quiet" — and
  `no_text_in_image` is forced on regardless of what any upstream field says.
  Every asset is a `VISUAL_PLATE`, and the column records it.
- **Provider-specific prompt wording lives in `app/providers/`.** `PromptAdapter`
  is a Protocol beside the others. Gemini folds exclusions into the instruction
  because it has no negative field; Leonardo keeps them apart because it does.
  Same meaning, different packaging (ADR-005).
- **Generation is database-backed jobs, not graph nodes** (ADR-012). No gate,
  tens of seconds of latency, partial failure as a normal outcome, per-provider
  retry. It joins the explicit-status discipline the app already uses.
- **Concurrency needs its own session.** `run_batch_in_background` opens one per
  job; `GenerationService.run_jobs` is sequential. Sharing an `AsyncSession`
  across gathered tasks raises "Session is already flushing".
- **Commit before scheduling.** A background task opening its own session can
  start before the request's transaction commits and find no jobs at all.
- **Tests never call a live provider.** The suite runs on `IMAGE_PROVIDERS=mock`,
  and the Gemini adapter is covered by driving it with a fake SDK client.

Previously: **Milestone 5 complete and verified** — the Creative Director and
the two human gates. Rules it established:

- **Distinctness is measured, not hoped for.** `assess_diversity` compares the
  structured *choices* (angle, subject, environment, composition, lighting,
  style) with Jaccard overlap and regenerates once above `SIMILARITY_LIMIT`.
  Deterministic set overlap, never clustering: the question does not need a
  model, and a model would make the answer unrepeatable. Do not compare prose —
  two directions can be worded very differently and be the same poster.
- **Confirmed campaign facts are pinned, not requested.** `_pinned_facts`
  overwrites the model's `cta` and `key_message` with the Campaign
  Specification's after *both* model calls. Asking a model to reproduce a fact
  is not the same as it reproducing one; the headline stays the model's to
  write, the facts do not.
- **Strategy and execution are separate decisions.** `CreativeDirection` is
  what we would say and why; `CreativeSpecification` is how to build it. Two
  models, two tables, two gates. Collapsing them makes the first gate
  meaningless.
- **The creative stage is its own graph on a derived thread**
  (`"{campaign_id}:creative"`, `build_creative_graph`). Extending the discovery
  graph in place would have reopened every paused Milestone 3 conversation
  against a new schema.
- **A gate is open when the graph is parked on its node**, not only when an
  interrupt has materialised. `aupdate_state` — how a human edit reaches the
  graph — starts a checkpoint where the gate node has not re-run, so reading
  the interrupt payload alone reported no gate and stranded an edited
  specification with nothing to approve. See `_pending_gate_kind`.
- **Milestone 5 stops at the approved specification.** No image is generated on
  approval. Milestone 6 reads the approved row from the database.

Previously: **Milestone 4 complete and verified** — reference intelligence and creative
context. Rules it established:

- **Learn the style, never copy the design** (ADR-011). `ReferenceAnalysis`
  has no field that could hold reproducible content, the prompt says so, and
  `sanitise_analysis` strips quoted text and trademarks from model output.
  Do not add a field for verbatim text, logos, coordinates or font families.
- **`CreativeContext` is the single assembly point.** Milestone 5's Creative
  Director consumes it; it must not re-derive brand rules or re-weight
  preferences for itself.
- **Campaign references are not brand assets.** Inspiration for one campaign
  versus the brand's approved identity — separate tables, separate meaning.
- **Preference weights are derived, never supplied.** Picks are stored;
  `VisualStyleProfile.from_sources` recomputes on read, so adding a reference
  reweights without the user re-picking. Deterministic, not learned.
- **The multimodal abstraction already existed.** `LLMProvider.structured`
  takes `images: tuple[ImageRef, ...]`. Do not add a second mechanism.

Previously: **Milestone 3 complete and verified** — campaign discovery. The LangGraph
campaign workflow is now a live product surface. Rules it established:

- **The CAMPAIGN SPECIFICATION (`CampaignBrief`) is the source of truth.** A
  prompt never is. Milestone 5+ compiles *from* it.
- **A human edit is never overwritten by recompilation.** Edits are marked
  `edited_by_human` on the field's `FieldAssertion`, written back into graph
  state as well as the database, and `campaign_brief_builder` carries them
  forward untouched.
- **Stated ≠ inferred.** "I think it's for architects" is recorded as
  `INFERRED`; only what a user asserts outright is `STATED`. Never collapse them.
- **`thread_id` comes from a scope-checked campaign row**, never a request
  parameter (M1_SECURITY_AUDIT A-5).
- **`AsyncPostgresSaver.setup()` runs at startup only.** It issues
  `CREATE INDEX CONCURRENTLY`, which waits for every open transaction — calling
  it per request deadlocks the request against its own session.
- **Alembic must not see LangGraph's tables.** `migrations/env.py` excludes
  them; without that, autogenerate proposes dropping every paused conversation.

Previously: **Milestone 2 complete and verified** — brand CRUD, document ingest
(upload → extract → chunk → embed → pgvector), AI brand-fact extraction,
retrieval, and the Brand Brain UI. Two rules it established:

- **`BrandProfile` holds confirmed facts only.** Model output becomes an
  `ExtractedFact` with status `PROPOSED`; only a human accepting it makes it
  brand truth. Never merge extraction output into the profile directly.
- **`BrandKnowledgeRetriever` is the single entry point to brand knowledge.**
  Milestone 4 campaign nodes call it; they do not query `brand_chunks`. It
  scopes by organization *and* brand — either filter alone is a leak.

Previously: **Milestone 1 complete and verified.** Migration 001, dev-stub auth behind a
replaceable `AuthProvider`, organization-scoped repositories, org/project CRUD,
`LocalStorageProvider`, and the Next.js shell. Risk R-2 is closed — the
LangGraph Postgres checkpointer round-trip is proved by a two-process spike
(`docs/R2_CHECKPOINT_SPIKE.md`), and every checkpointer must now be built via
`app/graph/serde.py:checkpointer_kwargs()`.

Read before changing anything: `ARCHITECTURE_REVIEW.md` — its §6 (scope cuts),
§8 (deferred) and §9 (milestone boundaries) are binding for the 9-11 day build.

`M1_SECURITY_AUDIT.md` records the security audit of Milestone 1. Two rules it
established bind later milestones: **identity is the IdP subject, never the
email** (§A-1), and **Milestone 4 must resolve a campaign through the scoped
repository before deriving a checkpoint `thread_id` from it** (§A-5), because
the checkpointer has no concept of an organization.

Next: nothing scheduled. See `M10_FINAL_REPORT.md` for status, limitations and
the future roadmap.

### Environment note

This repository lives in `~/Projects/campaign-os`, **not** on the Desktop.
`~/Desktop` is iCloud-synced, and syncing a Python venv plus `node_modules`
(~28,000 files) pinned `fileproviderd` at over 100% CPU and made a single
Python import take four minutes. Do not move this project back under
`~/Desktop` or `~/Documents`.
