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
      mock/ gemini/ local/      (leonardo/ tavily/ supabase/ are not built)
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
- **Print is out of scope and says so.** `COMPOSABLE_CHANNELS` is the six
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

**UI-2C complete** — all sub-phases A through F. Rules F established:

- **The canvas is a preview; the renderer is the truth.** The browser draws
  `LayoutSpec` geometry faithfully and cannot reproduce Pillow's line breaking,
  hinting or scrim alpha — so it is labelled `Preview`, and the final asset is
  what the server returns. A screen that let the two blur would undo ADR-006's
  whole claim.
- **Text size is a fraction of canvas height, so the canvas is a container.**
  `container-type: size` makes `1cqh` mean exactly what `text_style.size` means,
  which is how a headline set at `0.075` stays 7.5% of the frame at every
  breakpoint with no resize listener and no pixel state in React to drift from
  the spec.
- **`PATCH /composition` refuses a blocking edit outright.** It does not save a
  broken layout with a warning, so the canvas shows the last accepted state and
  a refusal is reported in the server's own sentence. Local geometry is shown
  while dragging because "is this rectangle inside that rectangle" is
  arithmetic about numbers the layout already carries — not a validation rule
  invented in the browser.
- **`available_channels` is the composable set *minus* the composed ones.**
  Reading it alone hid every channel the campaign already worked on. The union
  with `composed_channels` is the real set, derived rather than restated.
- **A size is shown only for a channel the app has really seen one for.**
  `CHANNEL_DIMENSIONS` lives in the backend domain and no endpoint publishes it,
  so an uncomposed channel says "compose to add" rather than a number this app
  invented.
- **A lock is an affordance plus a sentence; the refusal is the truth.** The
  composition API projects no per-element capability descriptor, so `locksFor`
  mirrors `PROTECTED_ROLES` and the two guards in one documented place. It
  drives a padlock and an explanation, never a claim — if it ever disagrees with
  the server, the server's rejection is what the user reads.
- **A control is offered only where the server accepts it.** `editableFields`
  mirrors `_editable_fields`: a size control on a logo would be a knob that
  quietly does nothing.
- **Compose gets the full width, and the context rail steps aside.** Every other
  stage is reading and earns the rail; Compose is a production workspace with
  three zones of its own, and a fourth column squeezed the canvas to ~200px.
  Nothing is lost — the campaign, brand, market and version are stated on the
  final-asset panel, where they belong to the deliverable.
- **One title per panel.** The collapsible carries it below `xl` and a plain
  label carries it at `xl`; rendering it inside the panel as well put "Layout
  check" on screen twice on a phone.

Rules the earlier sub-phases established:

- **Version facts come from rows that stamp their own version.**
  `GeneratedAssetView`, `GuardianResultView`, `GenerationView` and
  `SpecificationRevisionRow` each carry the plan version they belong to, and
  they cannot disagree. `/creative` cannot be used for this: it reads the
  creative graph's checkpoint, and on a revised campaign it reports the version
  the *gate* approved — a benchmark campaign returns v2 while the approved plan
  is v3 and every plate was built from v3. That is not a gap, it is a wrong
  number, and a version timeline built on it would be confidently false.
- **A version appears because a row carries its number**, never because a gap
  in the sequence implies one. A live campaign's v1 exists in the database with
  nothing pointing at it, so the timeline's earliest entry is v2 — which is
  therefore *not* called "the initial creative plan". Only v1 is, because only
  that one is true by definition.
- **A version never inherits another's brand verdict.** `versionBrandStatus`
  reads checks stamped with that version alone; a version nobody checked says
  "Not brand-checked", which is a different statement from a failure. Approving
  a revision produces neither a visual nor a verdict, and the screen says both
  out loud — they are the two things a reader is most likely to assume and most
  likely to be wrong about.
- **No author, anywhere.** `SpecificationRevisionRow` has no `requested_by` and
  the API projects none, so a version reads "Revision recorded". The version
  history is the surface people would cite in an argument about what happened
  to a campaign; it is the worst possible place to invent a name.
- **Structure only where the API takes structure.** `POST /revision` accepts
  one string, so the writing prompts compose that string and nothing more.
  Field-level KEEP/CHANGE/ADD/REMOVE editing is real and lives on the *proposed
  plan*, because `PATCH /revision/delta` is the one endpoint that accepts a
  per-field value.
- **A protection is stated once.** `delta.keep` normally repeats
  `locked_fields`; listing both reads as two protections where there is one, so
  the stronger statement wins — "locked" says it could not have changed, "kept"
  only says it did not.
- **Localization preservation is structural, not observed.** Region, language
  and audience live on the `CampaignBrief`, and a revision writes a
  `CreativeSpecification`, so "the market did not change" is a fact about the
  schema rather than a hopeful reading of one delta. The language renders
  through `displayLanguage` — a brief stores "en", which is not a language to a
  reader.
- **One verdict per object, not one string per page.** Three scopes
  legitimately carry a brand standing on the refine screen — the checked plate,
  the creative being refined, and the plan version. The rule UI-2C-D
  established is about two verdicts for *one* object side by side, and the test
  that guards it is scoped accordingly.

- **Generation fans out over providers, not over directions.** `GenerationView`
  carries no direction id, ordinal or title anywhere, so a slot is titled by
  its provider. "Direction 01" over a plate would be an association the backend
  never made — and one a reader would believe, because it is the vocabulary the
  previous screen taught them.
- **One slot per provider, showing its latest attempt.** The batch contains
  every superseded retry, so rendering `jobs` as a list showed the same
  provider three times with two stale failures.
- **The mock provider is named as a demo generator.** "Is this real output?" is
  the first question anyone watching has, and an offline demo dressed as a
  model answers it wrongly. `isOfflineProvider` drives a plain sentence beside
  the plate.
- **Only facts the API carries.** No request id, no seed, no provider latency —
  none exist, and an empty row labelled "Request id" implies one existed and
  was lost. Elapsed time is derived from `started_at`/`finished_at` and shown
  as "Took", never as a latency it is not.
- **A failed evaluation is not a low score.** `status` separates "not judged"
  from "judged badly"; the unjudged get their own section that says so. A
  plate nobody could score must never render as a bad one.
- **The chain is shown, not just the verdict.** Dimension weights and
  `disposition_reasons` sit behind a disclosure, because a bare "REJECT" is
  exactly the unaccountable verdict the architecture was built to avoid.
- **`NEEDS_REVIEW` is not `NEEDS_REVISION`.** Evaluation's disposition and the
  guardian's verdict are different enums on different surfaces asking different
  questions. Wording them alike tells a reader the two stages agreed.
- **A check decided by code is not a check decided by a model.** `deterministic`
  is carried onto the screen in words: a prohibited claim found by string
  matching is a fact, a tone judgement is an opinion.
- **"Why it matters" is ours and says so.** The backend has no such field, so
  the sentences are fixed, per known check id, and attributed to Campaign OS —
  never set beside the model's own `detail` as though it said them. An
  unrecognised check gets nothing rather than a platitude.
- **A verdict is said once per card.** It was a heading and a badge, and then
  the backend's `summary` turned out to be the verdict label again for a clean
  pass — three statements of one fact, which reads as three judgements that
  happen to agree. The supporting sentence is the backend's when it adds
  something, ours when it does not.
- **A check in flight is not a failed check.** Every non-`COMPLETED` row used
  to render as an error, so a legitimately running guardian read as a broken
  one for as long as it took.
- **One next action per question.** Both the generate and evaluate pages
  carried a run control in the header *and* in the studio, with different
  scopes and different labels. The studio owns it now, because it is what knows
  what it would act on: "check the remaining two" passes exactly those two ids.
- **The brand review and refinement share a page without echoing.** Separate
  headings, separate busy states — a brand check used to relabel "Propose a
  revision" as "Thinking…" — and one thread between them: "Refine this visual"
  attaches `source_asset_id`, and says on screen that it did.
- **A broken image is stated, not captioned.** `Plate` renders a failure in
  words, because an `<img>` that cannot load renders as its own alt text and
  reads like a description of a picture that is merely dark. A verdict beside
  an image nobody can see has to say the image is missing.
- **A status badge is its own worst backdrop.** `StatusBadge` puts the word at
  the full token on a 10% wash of the same token, so the two move together and
  the ratio is far tighter than the same word on the page. Measured there,
  light `warning` sat at 4.38 and `success` at 4.47 — both readable-looking,
  both failures.

- **One mapping layer per stage, not interpretation in the JSX.**
  `lib/creative.ts` owns every reading of a creative field. Three cards that
  each interpret `strategic_rationale` for themselves are three cards that
  drift apart.
- **A field of the plan is not a field of the direction.** `visual_story`,
  `camera` and `mood` belong to `CreativeSpecification`; a concept card cannot
  show them and must not substitute a neighbouring field under the same
  heading. That is a lie told in the user's own vocabulary.
- **Agreement is not a difference.** The comparison marks an axis `differs`
  only when the routes actually say different things, and shows what they share
  separately.
- **An override is a sparse diff.** Absent or null channel copy means inherit,
  not "no headline". Resolved in one place, because four independent `or`
  chains is how the screens came to disagree about the approved words.
- **Read `locked_fields` from the specification, never a copied constant.** A
  hardcoded list disagrees with the backend the day the backend changes.
- **A closed gate and a missing permission are different sentences.** "Not
  chosen" on an open gate misreports the state to the person who simply cannot
  approve.
- **Colour derived from data is not artwork.** The palette band is
  `direction.palette`, labelled as a stated palette. No imagery exists at the
  direction stage and none is invented.
- **Keep the routes after the choice.** The set still holds all three, and a
  decision a person cannot read back is a decision they cannot defend.

- **The workspace is three columns, and the middle one is the work.** Meridian
  left, work surface centre, campaign context right (`AppShell.aside`), all
  owned by the campaign layout so none of it resets between stages. Below
  1280px the context stacks *after* the content, which is the right reading
  order, not a drawer that hides it.
- **One next action, in one place.** The context rail owns it on every stage.
  The command centre deliberately no longer repeats it as a hero — two
  next-action affordances on one screen teach a person to trust neither.
- **A market fact is useless without its implication.** `creativeImplication`
  turns each fact into what it asks of the creative. Templates over real
  values, never invented data: a field with no value produces no instruction.
- **A confirmed brief must still be visible.** `POST /discovery/start` answers
  409 once a campaign is confirmed, so there is no `DiscoveryTurn` — and the
  brief screen rendered a permanent skeleton for every seeded campaign, hiding
  the document the whole pipeline is built from. The snapshot now adapts the
  confirmed specification through the same rendering path.
- **`field_assertions` mixes both vocabularies.** A real specification carries
  `campaign_objective` *and* `audience` *and* `target_audience`. A single-name
  lookup silently finds nothing for half the rows, so every row tries each
  known alias.
- **`not_applicable` is an answer, not a gap.** Reporting it as "still needed"
  asks someone the same question for ever.
- **Highlight the field being asked, not every open one.** `missing` is every
  remaining field; `question.field` is the one in play.
- **Show the refusal beside the takeaway.** ADR-011 is only checkable when
  `not_transferable` sits next to `style_takeaways` on the same card.
- **Absent characteristics are not drawn.** `ReferenceAnalysis` has no texture
  and no depth field. A chip nobody's model produced is a fabricated
  observation about someone else's artwork.

**UI-2B complete** — product home, projects, brands and the campaign command
centre. Rules it established:

- **Every number is counted, never estimated.** Campaign, brand, market and
  claim counts are the lengths of lists the page actually fetched. Where the
  data does not exist the section says so: there is no activity endpoint, so
  home shows "Recent work" from `created_at` rather than an invented feed.
- **No pin without a campaign.** The Atlas hero plots only markets derived from
  real specifications, and renders a bare plane with a sentence when there are
  none. A decorative pin on a product about locality would be the most
  dishonest thing the interface could do.
- **Provenance is checked before it is claimed.** The command centre's strip
  emits "constrained by the Brand Brain" only when guardrails are non-empty,
  "style learned from N references" only when analyses exist, and distinguishes
  what a model proposed from what a person approved. A strip that narrates
  unconditionally is decoration pretending to be an audit trail.
- **`unrecorded` is not `inferred`.** A specification value with no
  `field_assertion` is recorded without a stated source — not a guess. The
  benchmark seeds specifications directly and so carries no assertions;
  discovery-built campaigns carry real `stated` and `inferred`. The Local
  Market panel reports that difference rather than smoothing it over.
- **A project is a scope, not a page.** `projects/[projectId]/layout.tsx`
  states project, brand, markets and campaign count on every screen beneath it.
  A project row holds none of that — it is all derived from the organization's
  campaigns filtered by `project_id`.
- **Confirmed, inferred and unknown are the organising idea of a brand.**
  Brand Core counts `field_status[].knowledge` and surfaces facts awaiting a
  human decision, because only a person accepting a fact makes it brand truth.
- **An empty panel names its gap.** And emptiness is passed in, not inferred
  from `children`: a panel whose four children each return null still has four
  children, so a truthiness test reports content for a blank box.
- **A control nobody can use is not offered.** An approval gate shown to
  someone without approval rights becomes "this needs someone with approval
  rights" plus a read-only route in. Presentation only — no endpoint checks a
  role (H-5).
- **Markets cost one request per campaign.** There is no aggregate endpoint, so
  home and project resolve specifications with a bounded fan-out. Every
  campaign is resolved rather than the first few, because a partial sweep makes
  the per-market counts wrong, and a wrong count is worse than a slow page.
- **Measure contrast on a settled page.** Sampling immediately after a theme
  switch reports failures that are only in-flight `transition-colors` values.

**UI-2A frontend foundation complete** — application shell and information
architecture. The redesign's first stage; `docs/UI_UX_VISION.md` is the brief.
Rules it established:

- **The information architecture lives in `src/lib/nav.ts`.** One declaration
  of every destination and of the campaign journey. Screens read it; they do
  not each hold a copy of "where does Generate live", which is how the audit
  found stages that could be reached but never returned from.
- **Persistent navigation is a route layout, not a shared component.**
  `app/campaigns/[campaignId]/layout.tsx` is a client component, so it is not
  unmounted between stages: the Meridian, the organization and the campaign's
  identity survive a navigation. It also removed eight copies of the shell,
  eight `/me` requests and eight independently-invented loading gates.
- **A node declares what backs it.** `{kind:'stage'}` reads a real entry from
  `CampaignOverview.stages`; `{kind:'optional'}` is for a destination with
  working endpoints and no stage row, like Inspiration. Rendering an optional
  node with a stage state would be inventing backend data.
- **A missing summary means "available", never "not started".** With no
  overview the rail still renders every node. Defaulting to PENDING would tell
  someone their campaign had not begun because one request timed out.
- **A blocked stage stays a link.** The backend decides what a stage accepts; a
  person may look at one that is not ready. Refusing navigation in the UI is
  how the product became one-way.
- **The layout owns the `h1`.** Campaign identity is the page's one top-level
  heading; each stage screen renders `h2` and down. Eight pages previously each
  opened a new document with the title the header had just said.
- **Capabilities, not roles.** Screens ask `can('approve')`. And the limit is
  written down rather than glossed: no endpoint differentiates by role today,
  so hiding a control is presentation, not access control. Nothing may claim
  RBAC until the backend enforces it (audit finding H-5).
- **Localization is rendered by one component.** `PlaceStamp` displays
  `region`, `language` and `timing_occasion` identically everywhere and draws
  nothing when they are absent. It must never parse them into structure the
  domain does not have — `region` is one free-text string, not city and state.
- **Motion is CSS until a surface needs more.** Two keyframes and four duration
  tokens cover the whole vision document's motion table. Framer Motion is
  adopted at the first surface that needs orchestrated animation, not before.
- **A nav item must lead somewhere real.** `/app/projects` was listed for a
  route that was never built — a 404 in the primary navigation. A test now
  asserts every entry against the routes that exist.

**UI-1 frontend foundation complete.** The design system, not the redesign.
Rules it established:

- **A token is defined once, in `globals.css`, for both themes.** Colour,
  radius, elevation and layout all resolve through CSS variables that
  `tailwind.config.ts` exposes by name. A value that exists in one theme only
  renders as `transparent` in the other.
- **Status colour is a token, never a palette shade.** `emerald-400` and its
  siblings were hard-coded across 99 class usages; they are dark-background
  shades and measured roughly 1.8:1 on the light theme — status words a
  light-mode reader could not read. `success`/`warning`/`danger`/`info` resolve
  per theme. The whole product now measures at or above 4.5:1 in both.
- **Status is never carried by colour alone.** Every `StatusBadge` carries a
  word. A colour-blind reader and a washed-out projector are both real, and a
  test pins this.
- **The typeface is committed, not fetched.** `next/font/local` against woff2
  files in the repository, because CLAUDE.md §3.5 requires the demo to run with
  no network forever and `next/font/google` fetches at build time.
- **`extend`, never replace.** The numeric spacing and base type scales are
  load-bearing across thirteen screens. New code uses the named tokens; existing
  code keeps rendering byte-identically until its own phase.
- **A primitive earns its place by repetition.** Button, Card, Field and the
  rest each replaced a pattern already copied dozens of times. No Dialog and no
  Tabs were built, because the product contains neither — an unused abstraction
  fails the Definition of Done's first line.
- **Never name a shadow after a colour.** `boxShadow.card` beside `colors.card`
  made Tailwind resolve `shadow-card` as a shadow-*colour* utility and emit an
  invisible white shadow. Token namespaces collide silently; only the compiled
  CSS shows it.
- **Focus is a global rule, not a per-component one.** There was no focus
  styling anywhere before UI-1. One `:focus-visible` rule covers every
  interactive element, including the ones later phases add.

**Authentication foundation complete.** Rules it established:

- **The provider answers "who?", never "may they?"** `AuthProvider` returns an
  identity; membership and organization scope are resolved in
  `app/api/deps.py` and are byte-identical in dev and production. Swapping the
  identity provider must never touch the part that guards data.
- **Identity is the subject.** `users.auth_subject` binds to Supabase's `id`.
  There is no fallback to email anywhere — an email can be reassigned between
  people, and that is how one person inherits another's memberships.
- **A token is verified by asking Supabase**, not by verifying a JWT locally
  with a shared secret, which Supabase itself recommends against. Local
  verification also cannot see a revoked session until it expires.
- **Nothing retains the credential.** The verification cache is keyed by a
  SHA-256 digest; logs carry an exception type and a status code and nothing
  else; `AppError.detail` is log-side only and never serialised.
- **The anon key is public and the service-role key is not.** Auth uses the
  publishable key because the request already carries the caller's own token;
  a service-role key there would be a standing escalation for no benefit.
- **Dev stub is load-bearing, not legacy.** The offline demo must keep running
  with no identity provider, no keys and no network, forever.

**Pre-deployment audit fix pass complete.** The audit is in this file's history
and its findings are closed or explicitly deferred below. Rules it established:

- **The rows are the product state; the checkpoint is execution state.**
  `CreativeStageService.current()` falls back to reading `creative_direction_sets`
  and `creative_specifications` when no checkpoint exists, because `_project`
  exists to write graph state *into* those tables for the UI to read (ADR-004) —
  reading them back is the same direction of flow, not a second source of truth.
  The benchmark's nine campaigns are row-seeded and never ran the graph, so they
  had reported no creative at all while the database held approved directions and
  an approved plan. `gate` and `gaps` stay absent in that view rather than
  guessed: a gate is open when the graph is *parked on its node*, and there is
  nothing parked, so reporting one would draw an Approve button with no
  checkpoint to resume.
- **A re-entry guard that cannot see a row is not a guard.** `_advance` checked
  `existing.values` — the checkpoint — so a campaign whose creative exists only
  in the tables took the "start from scratch" branch, and `upsert_version` wrote
  the Creative Director's fresh output over an approved, human-decided version 1.
  Two fixes, because one was not enough: the service refuses to start when a
  direction set row exists, and the repository refuses to *replace* an approved
  row's payload at all. Idempotent is not the same as overwriting — the graph
  re-projects identical state many times, and that must stay a no-op.
- **Role enforcement is a dependency, not a habit.** `app/api/authz.py` is the
  authority and `lib/capabilities.ts` is its mirror; a test asserts they agree.
  Twenty-nine mutating routes depend on `require(capability)` *instead of*
  `PrincipalDep`, so the check cannot be forgotten separately from getting hold
  of the caller — and a test reads the routers and fails on any mutating route
  still reachable with a bare principal. The two creative gates check the
  **decision** rather than the route, because approving and asking for changes
  are different rights held by different roles.
- **Authorization narrows tenancy; it never replaces it.** Membership is
  resolved first and every repository still filters by organization. So `403`
  means "you belong here and lack the right" and `404` still means "not yours" —
  the case where existence is the secret.
- **"Nothing is waiting on a person" is not "nothing is happening."** The
  overview nominated a next stage only from `(ATTENTION, FAILED, PENDING)`, so a
  campaign mid-generation had none, and the workspace reads a missing next stage
  as complete. It now nominates the first stage that is not `DONE`, and the card
  says which of the four unfinished states that is. It had been announcing "This
  campaign is complete" while the same payload carried `generation: RUNNING`.
- **Align by identity, never by position.** The Compare table read
  `dimensions[index]` across evaluations and filled gaps with `?? 0` — so a
  six-dimension evaluation showed its scores under the first six labels and four
  fabricated zeroes, coloured as bad scores. `aggregate_score` renormalises over
  the dimensions present precisely so a partial evaluation is not a zeroed one;
  the screen now says "not scored" and the union of dimensions is the row set.
- **A name in an environment variable is not a capability.** Every provider is
  constructed at startup, so an unbuilt one is a boot failure naming the
  variable — which §5 of DEPLOYMENT.md had always claimed and only the LLM and
  embedding seams actually did. `/v1/health` reports `provider_status` — what
  *constructed* — beside `providers`, the configured names, and an unavailable
  seam degrades the status. It had answered `ok` with `storage: supabase` while
  the adapter did not exist.
- **Supabase storage is a seam, not an option.** `local` is the only storage
  provider in this build, so the documented production environment now selects
  it and multi-instance deployment means a shared volume. `tests/
  test_deployment_startup.py` builds `Settings` from the block in DEPLOYMENT.md
  §7 and constructs every provider it names, so the documented deploy cannot
  drift back into one that does not boot. It was two startup failures deep.
- **Idempotency is derived, not supplied.** There is no `Idempotency-Key` header
  and there never was; `generation_jobs.idempotency_key` is computed from
  `(prompt, provider, model, attempt)` and is `UNIQUE`, which is stronger — it
  holds for a client that sends nothing, and the attempt number lets a
  *deliberate* retry through where a replay is refused. The document was
  corrected to describe the mechanism that exists.
- **Paginate what grows with the tenant; leave alone what grows with a
  campaign.** `/projects`, `/brands` and `/campaigns` are keyset-paged on the
  column each was already sorted by, so no screen's order changed. The
  campaign-scoped lists are not paged, because a cursor there would be a knob
  with nothing behind it. `next_cursor` is additive, so every existing caller
  kept working.
- **A cursor is opaque, so it must be tagged.** One minted for a timestamp-keyed
  list and replayed against a name-keyed one is refused as a bad cursor. Postgres
  will not compare `text > timestamptz`, so without the tag it was a 500 — found
  by a test written to assert the opposite.
- **The document is asserted against the app, in both directions.**
  `tests/test_api_spec_matches_routes.py`. API_SPEC.md had 16 endpoints that did
  not exist, 46 that were undocumented, and a polling contract naming a 404. The
  mechanism already existed for `.env.example` and had simply never been pointed
  at the API. Endpoints an earlier draft specified are listed as deliberately
  absent *with the sentence in the document that disowns them*, so the list
  cannot become a place to hide things.

**Deployment readiness pass complete** — the repository is prepared for a first
hosted deployment. Nothing about the product or the workflow changed. Rules it
established:

- **A build-time variable is baked, so the build must refuse rather than
  default.** `API_BASE_URL` is inlined into the browser bundle by `next build`
  and no runtime environment can correct it afterwards, so `next.config.mjs`
  throws when it is missing and refuses a loopback origin unless
  `ALLOW_LOOPBACK_API_BASE_URL=true` says the build really is a local smoke
  test. The old default produced a site that built cleanly, loaded perfectly and
  could reach nothing, because the browser resolves `127.0.0.1` against the
  *visitor's* machine. `next dev` keeps the default; that is what dev is for.
- **Production refuses configuration that is unsafe, not just absent.**
  `Settings._refuse_unsafe_production` rejects wildcard, empty and plaintext
  `CORS_ORIGINS`, a `DATABASE_URL` still on localhost, and `DEMO_MODE=true` —
  every one of which is a supplied, valid value that produces a deploy which
  comes up looking healthy. Absence was already covered; this is the other half.
- **The identity provider is a readiness seam like any other.**
  `DevStubAuthProvider` authenticates every caller as the same user and its
  constructor refuses `APP_ENV=production` — its docstring called that "a startup
  failure rather than a silent hole", and nothing constructed it at startup, so
  the process booted, `/v1/health` said `ok` with `auth: dev_stub`, and the guard
  fired as a 500 on the first authenticated request. `auth` now sits in
  `_SEAMS` beside the five providers. The architectural separation stands
  (ADR-016 — different module, different Protocol); what moved is the
  *readiness* question, which is a deployment question and belongs in one place.
- **`local` is the only storage provider, so the instance count is a
  constraint, not a preference.** One backend instance unless every instance
  mounts the same filesystem, and the volume must survive redeploys — an asset
  uploaded through one instance is a 404 through another, intermittently.
  Stated in DEPLOYMENT.md §4 as a constraint rather than implied by §5's table.
- **The documented deployment is executed, not read.**
  `tests/test_deployment_startup.py` parses the environment blocks out of
  DEPLOYMENT.md, builds `Settings` from them and constructs every provider they
  name — now for the production block *and* the recommended first deployment.
  Headings are matched by text, not number, because inserting a section
  renumbered them and a test that breaks on that reports the wrong thing.
- **The first deployment uses real auth and mock models.** Real Supabase, real
  database, real volume, `IMAGE_PROVIDER=mock`. It exercises every path that can
  go wrong in *hosting* — sign-in, CORS, signed media, the volume, migrations —
  while spending nothing. Going live on real models afterwards is three
  variables and a key, which is the point of the provider abstraction.
- **Supabase auth is implemented and offline-tested; it has never run against a
  real project.** That sentence stays in the documentation until someone has
  actually signed in. The provider does attempt a real call — an unreachable
  identity provider becomes a `401` with a reason, never a pass-through — but
  attempting is not the same as succeeding.

Deferred, with reasons:

- **PERF-3 — `OverviewService` stays sequential.** Gathering its ten stage reads
  would share one `AsyncSession` across concurrent tasks, which raises "Session
  is already flushing" — the rule ADR-012 and Milestones 6 and 7 already
  established. Concurrency here needs a session per task, which is a change to
  how the read model is constructed for a saving nobody has measured.
- **The four gaps UI-2C-E and UI-2C-F recorded** (below) are unchanged. Each
  needs a backend projection, which is new API surface rather than a fix.

Backend gaps recorded by UI-2C-F and not worked around:

**`CHANNEL_DIMENSIONS` is not published.** The layout engine, the prompt
compiler and the channel picker all need to agree about what an Instagram story
is, and the table lives in `app/domain/common.py` where the browser cannot read
it. Useful because a channel picker that cannot state a size before you compose
is a picker you have to guess at. Workaround: sizes are shown only for channels
a layout or a rendered asset has already given real dimensions for.

**No per-element capability descriptor on the composition API.**
`_editable_fields`, `PROTECTED_ROLES` and the two guards decide what an edit may
touch, and none is projected — so the editor mirrors them to decide which
controls to draw. Useful because a mirror can drift. Workaround: the mirror is
isolated in `lib/compose.ts`, drives affordances only, and the server's typed
rejection is what the user is shown.

**A brand asset projects no storage key.** The layout's logo element carries
one; `BrandAssetSummary` carries a signed `url` and no key, so the two cannot be
matched exactly and the preview picks the first asset of kind `logo`/`logo_mono`
— which is what `_logo_row` does. Only the preview is affected: the renderer
uses the key, so the file is always right.

Open backend gap, recorded by UI-2C-E and not worked around: **the revised
specification is not projected.** `RevisionStageService.RevisionView` holds
`revised_specification` and `_revision_view` drops it, returning only a `diff`
of the changed fields. So the refine screen cannot read the revised plan's
`locked_fields` — where `apply_revision` writes the five standing locks — and
"what is protected" is the product's own differentiator. Workaround in use:
`delta.keep` and `delta.explicit_unlocks`, which are per-revision truth and
always correct, plus `/creative`'s `locked_fields` on campaigns where that
endpoint's version is the current one. When both are empty the panel renders
nothing rather than a reassuring fiction. Separately, and deliberately not
added: no `requested_by` on a revision. See `M10_FINAL_REPORT.md` for status, limitations and
the future roadmap.

**Media access fixed** — the gap UI-2C-D recorded is closed. See ADR-017.
Rules it established:

- **A browser proves a media read with a signature, not a header.** Every media
  `url` carries `?token=…`: one resource kind, one row id, one organization,
  one user, one expiry, signed server-side. `Authorization` and
  `X-Organization-Id` cannot be set on an `<img src>`, so header-only media was
  unreachable from the page that renders it.
- **The reported bug was the smaller half.** "Multi-organization users see no
  plates" was what the dev stub happened to expose. The stub ignores the
  credential, so a single membership worked by accident; with a real identity
  provider *nothing* would have loaded for anyone. A fix that only added the
  organization to the query string would have looked right and failed on the
  day Supabase auth was switched on.
- **The token replaces transport, never authorization.** `media_access()`
  verifies the signature, checks kind and row id against the route, **re-reads
  membership**, and hands the route an ordinary `Principal`. The route resolves
  the row through the same scoped repository and reads the key from *it*. No
  key, path or filename is ever in a token — there is nothing to traverse.
- **Binding is the dependency, not a habit.** `media_access(kind, path_param)`
  cannot be satisfied by a token for another row or another route, so a route
  cannot forget to check what a signature was signed for.
- **Membership is authority, not history.** Losing a membership revokes every
  outstanding link immediately, rather than at expiry.
- **No shipped signing key.** Unset means one per process, so the offline demo
  and the tests configure nothing and no install ships a key that is the same
  everywhere. Production must set `MEDIA_URL_SECRET` — two instances with two
  generated keys reject each other's links, which presents as images that load
  on refresh and not before — and `Settings` refuses to start without it.
- **A URL variant is built by the server.** `url` carries a query string, so
  `url + "?download=true"` folds the flag into the token and 404s.
  `FinalAssetView.download_url` exists for exactly that.
- **Every media reference goes through `mediaUrl()`.** A bare API path in a
  `src` resolves against the *page* origin — the Next server, which serves no
  bytes. The moodboard did this and rendered a broken image beside a perfectly
  good analysis of it; a test now walks the components and fails on a raw one.

### Environment note

This repository lives in `~/Projects/campaign-os`, **not** on the Desktop.
`~/Desktop` is iCloud-synced, and syncing a Python venv plus `node_modules`
(~28,000 files) pinned `fileproviderd` at over 100% CPU and made a single
Python import take four minutes. Do not move this project back under
`~/Desktop` or `~/Documents`.
