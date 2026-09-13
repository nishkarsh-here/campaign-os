# ARCHITECTURE.md

Status: **Milestone 0 — contracts defined, no feature implementation yet.**
Last updated: 2026-09-11

---

## 1. Verified environment

Measured on this machine, not assumed:

| Component  | Found                                      | Consequence |
|-----------|---------------------------------------------|-------------|
| Node       | v24.18.0, npm 11.16.0                      | Next.js 15 fine. No pnpm — use npm. |
| Python     | 3.13.13                                     | Pin `>=3.12,<3.14`. |
| uv         | 0.12.10                                     | Package manager. No Poetry installed. |
| PostgreSQL | 18.3 (Postgres.app), running on :5432       | Primary datastore, local. |
| pgvector   | **0.8.1 available** (`pg_available_extensions`) | RAG needs no extra infra. |
| Redis      | 8.8.0 CLI present                           | Available if we ever need a queue. |
| Docker     | **not installed**                           | Nothing may require docker-compose to run. |
| Keys       | `GEMINI_API_KEY` set. No Leonardo/fal/Supabase keys. | Gemini is the only live provider today. |
| Ports      | 3000 and 8000 free                          | Default dev ports. |

Two facts drive real decisions: **there is no Docker**, so the dev story is
"local Postgres + uv + npm", and **pgvector is already available**, so Brand
Brain retrieval needs no vector database service.

---

## 2. System shape

```
┌──────────────────────────────────────────────────────────────────────┐
│  Next.js (App Router, TS, Tailwind, shadcn/ui)                       │
│  workspace · brand · campaign chat · approval gates · gallery · editor│
└───────────────────────────────┬──────────────────────────────────────┘
                                │  REST/JSON, typed from OpenAPI
┌───────────────────────────────▼──────────────────────────────────────┐
│  FastAPI                                                             │
│   api/          thin routers: validate, authorize, delegate          │
│   services/     use-cases; own transactions; start & resume runs     │
│   repositories/ DB access, org/project scope enforced here           │
│   graph/        LangGraph: nodes, edges, CampaignState, checkpointer  │
│   providers/    LLM · Image · Embedding · Storage · Search (Protocols)│
└───────┬────────────────────────────────────────┬─────────────────────┘
        │                                        │
┌───────▼──────────────────┐          ┌──────────▼─────────────────────┐
│ Postgres 18 + pgvector   │          │ Providers                      │
│  app tables (product)    │          │  mock (default, offline)       │
│  langgraph schema (exec) │          │  gemini · leonardo · local fs  │
│  brand_chunks (vectors)  │          │                                │
└──────────────────────────┘          └────────────────────────────────┘
```

Three layers, one direction of dependency: `api -> services -> {repositories, graph} -> providers`.
Nothing points back up. A node never imports a router; a repository never imports a service.

---

## 3. The central idea: specification over prompt

The failure mode of AI marketing tools is that "the prompt" becomes the program.
Prompts are unstructured, unversionable, undiffable and impossible to approve.

Here, the durable artefact is structured data, and the prompt is a *build output*:

> **Vocabulary.** The canonical business concept is the **CAMPAIGN
> SPECIFICATION**; its implementation type is `CampaignBrief`, exported also as
> `CampaignSpecification`. See the canonical vocabulary table in
> `docs/PRODUCT_SPEC.md` §1a — it is the single place that mapping is defined.

```
conversation
   └─> CampaignInputs        what the human actually wants (typed, validated)
        └─> CampaignBrief    THE CAMPAIGN SPECIFICATION: + brand, references,
            |                market context — all ambiguity resolved
             └─> CreativeDirection × 3      strategy options a human picks from
                  └─> CreativeSpecification the approved, complete creative plan
                       └─> ModelPrompt      per-provider, compiled, disposable
```

Consequences, and they are the point:
- A human approves a **CreativeSpecification** they can read, not a prompt blob.
- Switching image providers recompiles prompts; it does not lose strategy.
- A revision edits *fields* ("environment", "emotional tone") while provably
  preserving others ("product", "logo", "key message").
- Every generated asset is traceable to the exact spec version that produced it.

---

## 4. Architecture Decision Records

Each ADR states the decision, why, and what we give up. Where two options were
valid we took the simpler one that still supports the product vision.

### ADR-001 — Monorepo, two deployables
`backend/` (FastAPI) and `frontend/` (Next.js) in one repository.
**Why:** the API contract changes constantly in early milestones; one repo keeps
schema, generated TS types and UI in the same commit.
**Cost:** CI must be path-filtered. Accepted — Vercel and Railway both deploy
from a subdirectory.

### ADR-002 — Local Postgres + pgvector now, Supabase as a deployment target
`DATABASE_URL` is a plain Postgres DSN. Supabase *is* Postgres, so moving means
changing the DSN. Auth and Storage sit behind our own interfaces so the
Supabase-hosted versions can be swapped in without touching business logic.
**Why:** Docker is absent, Postgres 18 + pgvector 0.8.1 is already running, and
the demo must not depend on a cloud project being reachable.
**Cost:** we do not get Supabase Auth/RLS on day one; we write a small auth
adapter instead. Accepted — the spec explicitly says not to overbuild authz first.

### ADR-003 — LangGraph with a Postgres checkpointer; HITL via `interrupt()`
Human approval gates are the product, and they span HTTP requests, page reloads
and (during a live demo) process restarts. The graph therefore persists every
step to Postgres and pauses with LangGraph's `interrupt()`; the API resumes it
with `Command(resume=decision)` using the campaign's `thread_id`.
**Rejected:** in-memory checkpointing (loses a demo to one reload) and
"run the graph in one request and poll a status column" (cannot pause mid-graph).
**Cost:** the checkpointer owns tables we do not design, and state must stay
serializable. Accepted.

### ADR-004 — Two sources of truth, deliberately separated
- The **checkpointer** owns *execution* state: where the graph is, what it may resume into.
- **Application tables** own *product* state: briefs, directions, assets, approvals, history.

Nodes update `CampaignState`; designated nodes also call a repository to project
their output into application tables at commit points. The UI reads application
tables and never reads checkpoint internals.
**Why:** a checkpoint is an execution log — it is the wrong thing to query for
"show me every campaign in this project", and its shape is LangGraph's to change.
**Cost:** a projection step per persisted artefact. Accepted; it is ~5 lines and
it keeps the product queryable.

### ADR-005 — Provider abstraction with `typing.Protocol` + registry
`app/providers/base.py` defines five Protocols. `registry.py` maps env vars to
implementations. Business code receives providers by dependency injection and
cannot name a vendor.
**Why:** rule 5 of `CLAUDE.md`, and provider swapping is a stated product need.
**Rejected:** LangChain's model wrappers as the abstraction — that would make
LangChain's interface our domain interface, and it does not cover image
generation cleanly. We use LangChain only where it genuinely saves work.
**Cost:** a thin adapter per provider. Accepted.

### ADR-006 — AI renders the plate; deterministic code renders the brand
Generative models are unreliable at typography, logos, exact hex colours and
safe margins. So:
- **Image model** produces the *visual plate* (subject, environment, lighting, mood).
- **Pillow** composes headline, subhead, CTA, logo, brand colour blocks and
  legal line from a declarative `LayoutSpec`, and exports every channel size.

Rendering is a pure function: `(LayoutSpec, plate, brand assets) -> PNG`.
Same inputs, same pixels, every time.
**Why:** it is the difference between "an AI picture" and a brand-usable creative,
and it makes 8 channel variants a loop instead of 8 generations.
**Cost:** the browser preview and the server renderer are two implementations of
one layout language and can drift. Mitigated by keeping `LayoutSpec` deliberately
small and adding a parity test in Milestone 9. The server render is authoritative.

### ADR-007 — Background asyncio tasks now; Celery only if measured need appears
A run is started by an API call, executed as a FastAPI background task, and
tracked in a `campaign_runs` row with an explicit status. The frontend polls.
**Why:** Redis + Celery is a second runtime and a second failure mode for a
single-node app; the spec says "Celery if needed". The Postgres checkpointer
already gives us durability and resume, which is the part that actually matters.
**Cost:** a process crash mid-run leaves a `RUNNING` row; a startup sweep marks
orphans `FAILED` so they can be resumed rather than hanging. If we later need
multi-worker fan-out, the service boundary already exists to put a queue behind.

### ADR-008 — `CampaignState` is a Pydantic model, not a `TypedDict`
LangGraph accepts either. Pydantic gives validation at merge time, defaults, and
one definition shared with the API layer.
**Cost:** slight overhead, and reducer fields need `Annotated[...]`. Accepted —
catching a malformed node output at the node boundary is worth more than the
microseconds.

### ADR-009 — Structured LLM output is a provider concern, handled once
`LLMProvider.structured()` takes a Pydantic model and returns an instance of it,
handling JSON-schema constraint, retry, and a repair pass on parse failure.
**Why:** "model returned malformed JSON" is the most common runtime failure in
this class of system. Handling it in one place beats nine nodes each doing it
slightly differently.

### ADR-011 — Reference analysis extracts style, never content
A reference is inspiration, not a template. The boundary is enforced in three
places rather than trusted once:

1. **The schema cannot hold reproducible content.** `ReferenceAnalysis` has no
   field for verbatim text, logos, coordinates or font families, and
   `forbids_reproduction()` states the rule in code so a later milestone
   widening it is a visible change rather than a quiet one.
2. **The prompt states the rule** to the model.
3. **`sanitise_analysis` strips** quoted strings and trademarked names from
   whatever comes back, so a model that ignores the instruction still cannot
   smuggle a headline into the creative context.

Typography is recorded as *character* — scale, weight, classification, case —
never as an identified typeface: guessing a foundry's font from a JPEG is
unreliable, and reproducing it is the copying this forbids.
**Cost:** a genuinely useful detail occasionally gets stripped. Accepted; the
failure mode in the other direction is someone's design reappearing in a
client's campaign.

### ADR-010 — Types flow one way: Pydantic -> OpenAPI -> TypeScript
`openapi-typescript` generates `frontend/src/lib/api-types.ts` from the running
API's schema. Hand-written duplicate interfaces in the frontend are a bug.

### ADR-012 — Image generation runs as database-backed jobs, not graph nodes
A "generate creatives" request compiles prompts, writes one `PENDING`
`generation_jobs` row per provider and returns `202`. The providers are called
after the response; the frontend polls. Generation is deliberately **not** a
LangGraph node.

**Why:** the creative graph's value is the human gates — `interrupt()` and
resume across processes, proved in Milestone 5. Generation has no gate. What it
has is latency measured in tens of seconds across several providers, partial
failure as a normal outcome, and per-provider retry. A graph node would hold an
execution open for all of that, and "retry only the Leonardo job" has no natural
expression in a node that already ran.

**This is not a second orchestration mechanism.** An explicit job row with
`PENDING | RUNNING | COMPLETED | FAILED | CANCELLED` is the discipline the
application already uses for every long-running thing — document ingestion,
reference analysis, campaign runs (CLAUDE.md rule 7). Generation joins that
pattern rather than inventing one.

**Concurrency comes with its own session.** `run_batch_in_background` opens one
session per job and gathers them: an `AsyncSession` is not safe to share
between concurrent tasks, and sharing one raises "Session is already flushing"
the moment two providers write at once. `GenerationService.run_jobs` — the
single-session path — is therefore sequential by design.

**Cost:** an in-process background task dies with the process, so a job can be
left `RUNNING` if the server is killed mid-generation. Acceptable at this scale:
the row is still there, its status is still explicit, and a retry is one click.
A durable queue is the upgrade path if it ever matters, and nothing above
changes when it arrives.
**Rejected:** Redis plus a worker — real infrastructure for a demo-stage system
whose whole job pipeline fits in Postgres, and another service to keep alive
during a live demo.

### ADR-013 — Revision gates are rows, not graph interrupts
Milestone 8's two human decisions — approve the revision *plan*, then approve
the revised *specification* — are states on a `specification_revisions` row
(`PROPOSED → APPLIED → APPROVED`, or `REJECTED`), not `interrupt()` points in
the creative graph.

**Why:** an interrupt exists to pause an execution that is *already running*.
Milestone 5's gates needed one because the graph was mid-flight between
generating directions and building a specification. A revision has no such
execution: propose, approve, apply and approve again are four separate HTTP
requests with nothing running between them. Modelling that as a graph would add
a thread, a checkpoint and a resume path to represent state that four rows
already hold — and the thread would have to be a *new* one, because resuming
Milestone 5's creative thread against a schema it never saw is exactly the
"reopen an old conversation against incompatible state" failure this project
has avoided since Milestone 3.

**This is not a second campaign state model.** The gates are the same explicit
status discipline generation and evaluation use (ADR-012), on a row that is
already the revision's own record. `CampaignState` and the checkpointer are
untouched.

**Cost:** the revision loop cannot be resumed mid-decision the way a graph
interrupt can — but there is nothing to resume, because nothing is executing.
If a later milestone puts a long-running step *between* the two gates, that
step is the thing that needs a checkpoint, and it can have one without moving
the gates.

### ADR-014 — The layout is the edited artefact; the render is a versioned output
Milestone 9's `LayoutSpec` is the source of truth for a final asset. The PNG is
a *product* of it, produced by `app/services/renderer.py` and stored as a
`final_assets` row. Editing means changing fields on the layout and rendering
again; nothing in the system edits an image.

**Why:** an image cannot be reasoned about. Once a headline is baked into
pixels you cannot ask where it is, whether it clears the safe area, whether it
still says what the approved specification says, or what it would look like at
1080×1920 — you can only look. Keeping the recipe means `validate_layout` can
refuse a broken composition before a pixel is drawn, a channel variant is a
re-layout rather than a regeneration, and a re-render of an old layout version
produces the same file it produced before.

**Versions, never mutation.** An accepted edit writes a new `layout_specs` row;
a render writes a new `final_assets` row carrying the layout inline as
`layout_snapshot`. The snapshot is why a later edit cannot change what an
already-delivered asset claims to be: the id says which document it came from,
the snapshot says what it actually rendered.

**Composition is a product service, not a graph stage and not an agent.**
Rendering takes milliseconds, calls no model, has no human gate and cannot
partially succeed. A node, a thread and a checkpoint would represent state that
two rows already hold; a job row and a polling loop would be machinery with
nothing to wait for. The route renders synchronously and returns the asset.

**The editor is constrained on purpose.** `EDITABLE_ELEMENT_FIELDS` is a short
list: position, size, visibility, text, alignment, colour, case. The call to
action and the legal line carry approved facts and their *words* are checked
against the approved specification; the logo cannot be hidden. Everything else
a canvas app offers — drawing, new element types, layers, animation, multiple
pages — is absent, not unimplemented. A refusal is a typed `ValidationFailed`
with a sentence, never a silently dropped control, because an ignored edit
reads as an applied one.

**Cost:** the editor can only express what `LayoutElement` can hold. A user who
wants something the schema has no field for cannot have it, and adding a field
is a deliberate change with a migration behind it. That is the trade this ADR
buys the rest of its guarantees with.

**Typography limitation (recorded, not worked around):** the renderer uses a
brand-uploaded TrueType face when the Brand Brain has one, and Pillow's bundled
face otherwise. It does not identify, download or substitute a named typeface —
a brand whose guidelines say "Söhne" gets the fallback, and the render is
correct in layout but not in typeface. Naming a font we cannot license or
verify would be a worse answer than a documented fallback.

---

## 5. Reliability model

Every external call can fail, so failure is modelled rather than caught ad hoc.

| Failure | Handling |
|---|---|
| LLM timeout / rate limit | bounded retry with jittered backoff in the provider adapter; then a typed `ProviderError` |
| Malformed model JSON | schema-constrained decode, one repair attempt, then `ProviderError` (ADR-009) |
| Image generation failure | job -> `FAILED` with reason; router may fall back to the next configured provider; the run continues with whatever assets succeeded |
| All providers down | `mock` provider path stays available; the demo degrades to seeded assets rather than dying |
| Upload rejected | validated before write (MIME + magic bytes + size); typed 4xx, UI shows a specific message |
| DB error | transaction rolls back; run marked `FAILED` with the failing node recorded |
| Process death mid-run | startup sweep marks orphaned `RUNNING` runs `FAILED`; the checkpoint survives, so the run is resumable |
| User cancels | `CANCELLED`; no further node executes; partial artefacts stay visible and labelled |
| Revision loop runs away | `iteration_count` vs `MAX_GRAPH_ITERATIONS`; the graph exits to a human gate rather than looping |

Rule: a run never ends in an undefined state. Terminal status is always written.

---

## 6. Observability

Structured JSON logs with `run_id`, `campaign_id`, `node`, `status`,
`duration_ms`, `provider`, `attempt`. Never prompt contents at INFO, never
secrets, never user PII. Node timing and status are also written to
`campaign_runs.node_history` so the UI can show a real progress trail — the
progress indicator is backed by data, not by a spinner and hope.

---

## 7. Scope discipline

Deliberately **not** building: Kubernetes, microservices, Kafka, a Canva-class
editor, multi-tenant billing, a custom auth system, real-time collaborative
editing, or a model-training pipeline. Levels 1–3 of the delivery ladder
(`docs/ROADMAP.md`) must stand on their own; Level 4 never blocks a demo.
