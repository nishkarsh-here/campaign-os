# DATABASE_SCHEMA.md

Postgres 18 + pgvector 0.8.1 (verified locally). Migrations: Alembic, in
`backend/migrations/`. Supabase is the same engine — moving there is a DSN change.

## Conventions

- Primary keys `uuid` (`gen_random_uuid()`, `pgcrypto`). No sequential IDs in URLs.
- `created_at`, `updated_at` `timestamptz not null default now()`.
- Soft delete only where users can undo (`deleted_at`), hard delete elsewhere.
- **Tenancy.** Root tables — `projects`, `brand_profiles`, `brand_assets`,
  `brand_documents`, `brand_chunks`, `campaigns`, `memberships` — carry
  `organization_id` and are indexed on it. Descendant tables (briefs,
  directions, prompts, jobs, assets, evaluations, approvals, revisions,
  final assets) do **not** duplicate it; they are scoped by joining to their
  campaign or project. Denormalising the org id onto all 23 tables would add a
  second thing to keep true.
  The guarantee therefore lives in **one** place: a repository base class that
  takes `organization_id` and applies it — directly or through the join — to
  every read and every write. A parametrized cross-organization test covers
  every repository, so this cannot be forgotten in a route handler.
- Enum-like columns are `text` + `CHECK`, not Postgres enums — a CHECK is far
  cheaper to change than an enum type, and these values will change.

### The JSONB decision

AI artefacts (brief, direction, spec, evaluation) are deep, evolving documents.
Fully normalizing them now would mean a migration per prompt-tuning session.

**Pattern:** one row per artefact, with

- a `payload jsonb` column holding the Pydantic model, validated on write *and*
  on read (`Model.model_validate(row.payload)`), plus
- **promoted columns** for anything we filter, sort, join or foreign-key on, plus
- `schema_version int` so an old row can be migrated or refused explicitly.

This keeps the data typed at the application boundary (rule 3 in `CLAUDE.md`)
without pretending we know the final shape of a `CreativeDirection` today.
Artefacts users *act on individually* — directions, prompts, assets, approvals —
get their own table so they can be referenced by FK.

---

## Migration 001 — foundation (Milestone 1)

```sql
create extension if not exists pgcrypto;
create extension if not exists citext;
create extension if not exists vector;

create table organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table users (
  id uuid primary key default gen_random_uuid(),
  email citext not null unique,
  display_name text,
  auth_subject text unique,          -- external IdP subject (Supabase Auth later)
  created_at timestamptz not null default now()
);

create table memberships (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  role text not null check (role in ('admin','brand_manager','marketing','designer','viewer')),
  created_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table projects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  description text,
  created_by uuid references users(id),
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on projects (organization_id) where deleted_at is null;
```

## Migration 002 — Brand Brain (Milestone 2) — **APPLIED**

> **Brand cardinality decided.** `ARCHITECTURE_REVIEW.md` M-6 left open whether a
> brand belongs to an organization or a project. **A brand belongs to an
> organization.** An agency organization holds several brands and a project
> selects one. The `project_id` column sketched below was therefore *not*
> created: a nullable column nothing reads is the speculative schema the
> roadmap forbids, and adding it later is a purely additive migration.
>
> **Two tables were added beyond the original sketch.** `brand_facts` holds
> AI-proposed brand facts awaiting human acceptance — without it, extraction
> output would have to be merged straight into `brand_profiles.payload`, which
> is precisely the "AI guess silently becomes a confirmed brand fact" failure
> the milestone forbids. `brand_chunks` gained `brand_profile_id` (the sketch
> reached the brand only through the document) so retrieval can filter on brand
> directly rather than by join — the filter is on the hot path of every query.
>
> **Document status is per-stage**, not the generic job vocabulary:
> `PENDING → EXTRACTING → EMBEDDING → COMPLETED`, with
> `UPLOAD_FAILED`, `EXTRACTION_FAILED`, `EMBEDDING_FAILED`, `ANALYSIS_FAILED`.
> A failure has to name the stage for the UI to say what to retry.
>
> Applied as `migrations/versions/0002_brand_brain.py`; verified to run clean
> from empty and to downgrade. The sketch below is kept for comparison.


```sql
create table brand_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id uuid references projects(id) on delete cascade,
  name text not null,
  payload jsonb not null,            -- domain.brand.BrandProfile
  schema_version int not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on brand_profiles (organization_id);

create table brand_assets (              -- logo, product shots, fonts, palette swatches
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  kind text not null check (kind in ('logo','logo_mono','product','font','pattern','other')),
  storage_key text not null,
  mime_type text not null,
  width int, height int, bytes bigint,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table brand_documents (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  brand_profile_id uuid not null references brand_profiles(id) on delete cascade,
  title text not null,
  source_type text not null check (source_type in ('pdf','url','text','campaign')),
  storage_key text,
  status text not null default 'PENDING'
    check (status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
  error text,
  created_at timestamptz not null default now()
);

create table brand_chunks (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  brand_document_id uuid not null references brand_documents(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  metadata jsonb not null default '{}',
  embedding vector(1536),            -- dimension pinned per EMBEDDING_PROVIDER; see note
  created_at timestamptz not null default now(),
  unique (brand_document_id, chunk_index)
);
create index on brand_chunks using hnsw (embedding vector_cosine_ops);
```

> **Embedding dimension is a migration-level commitment.** Changing
> `EMBEDDING_PROVIDER` to a model with a different width requires a migration and
> a re-embed. The column width and the provider's `dimensions` property are
> asserted equal at startup so a mismatch fails loudly instead of at query time.

## Migration 003 — campaign discovery (Milestone 3) — **APPLIED**

> Created: `campaigns`, `campaign_runs`, `campaign_messages`,
> `campaign_specifications`, `campaign_references`. **Not** created: creative
> directions, prompts, generation jobs, assets, evaluations — those belong to
> Milestones 5+ and the sketch below keeps them for reference only.
>
> **`campaigns.draft_inputs`** closes gap M-1 from `ARCHITECTURE_REVIEW.md`:
> structured campaign inputs had nowhere to live while the interview was still
> running, since a specification does not exist until it ends.
>
> **`campaign_messages.sequence`** orders the transcript. `created_at` alone is
> not sufficient — a question and its answer are written in one flush and share
> a `now()`, so the tiebreak fell to a random UUID and the transcript could
> render the answer before the question.
>
> **`campaigns.thread_id`** is the LangGraph thread, unique, and always derived
> from the scope-checked campaign row.
>
> Applied as `migrations/versions/0003_campaign_discovery.py`; verified to run
> clean from empty and to downgrade.

## Migration 004 — reference intelligence (Milestone 4) — **APPLIED**

> Added to `campaign_references`: `status`, `analysis`, `analyzed_at`, `error`,
> `content_sha256`, `accepted_at`, `width`, `height`. Added to `campaigns`:
> `creative_preferences`.
>
> **`campaign_references` and `brand_assets` stay separate.** A brand asset is
> the brand's approved visual identity; a campaign reference is inspiration for
> one campaign. Merging them would let a mood board become brand truth.
>
> `creative_preferences` is a column, not a table: there is exactly one
> preference set per campaign, and a table would add a join for nothing. The
> stored value holds the user's *picks*; the weighted profile is re-derived on
> read so adding a reference reweights it without the user re-picking.
>
> `content_sha256` lets identical bytes reuse an existing analysis instead of
> paying for another multimodal call.
>
> Alembic does not autogenerate CHECK constraints, so the reference status
> constraint is added explicitly in the migration.
>
> Applied as `migrations/versions/0004_reference_intelligence.py`; verified to
> run clean and to downgrade.

## Migration 005 — Creative Director (Milestone 5) — **APPLIED**

> Four tables: `creative_direction_sets`, `creative_specifications`,
> `creative_approvals`, `creative_revisions`.
>
> **A set, not a row per direction.** Distinctness is a property of the three
> directions *together* — the diversity verdict describes the set — and the
> three are always generated, shown and replaced as a unit. Storing them
> individually would make "which three were shown together" a reconstruction.
>
> **Versions are added, never overwritten.** Both `creative_direction_sets` and
> `creative_specifications` are unique on `(campaign_id, version)`. Requesting
> changes writes version 2 next to version 1, so what a human saw when they
> decided is still on record. `creative_revisions` links the two versions with
> the feedback and the KEEP/CHANGE interpretation that produced the new one.
>
> **Strategy and execution are separate tables** because they are separate
> decisions. `CreativeDirection` is what we would say and why;
> `CreativeSpecification` is how to build it. Collapsing them would make the
> first gate meaningless.
>
> `creative_approvals` records both gates — `gate` is `strategy` or
> `specification` — with the decision, feedback and who decided. An approval is
> a fact about a human, so it is a row, never a flag on the artefact.
>
> Alembic does not autogenerate CHECK constraints; the gate and decision
> constraints are added explicitly in the migration.
>
> Applied as `migrations/versions/0005_creative_director.py`; verified to run
> clean, to downgrade, and `alembic check` reports no drift.

## Migration 006 — prompt compilation and generation (Milestone 6) — **APPLIED**

> Four tables, and the chain between them is the point:
>
> ```
> creative_specifications (approved)
>   -> canonical_prompts        one per compile, provider-neutral
>     -> model_prompts          one per provider/model
>       -> generation_jobs      one per provider attempt
>         -> generated_assets   what came back
> ```
>
> Every row below a specification carries `specification_id` and
> `specification_version`, so an asset can be traced to the approved plan
> without walking the chain — and a plate generated from a plan that has since
> been revised is visible as such.
>
> **Prompts are versioned, never overwritten.** `canonical_prompts` is unique on
> `(campaign_id, version)`, `model_prompts` on
> `(canonical_prompt_id, provider, model, version)`. The exact text a provider
> was charged for stays on record beside the asset it produced.
> `source_fingerprint` is a digest of the specification fields a prompt was
> compiled from: because compilation is deterministic, an unchanged plan
> recompiles to the same fingerprint and reuses its row rather than inventing a
> version that claims something changed.
>
> **`generation_jobs.idempotency_key` is unique.** A replayed request finds the
> existing job instead of charging twice. A deliberate retry increments
> `attempt`, which is part of the key, so it *is* a new charge — the distinction
> a user is making when they press Retry.
>
> **`generated_assets.kind` is explicit.** `VISUAL_PLATE` says what a raw model
> output is; logo, headline, CTA and exact colours come later from the
> deterministic renderer (ADR-006). A column recording the difference stops a
> later milestone treating a plate as a finished creative.
>
> `storage_key` is generated, never derived from anything a user typed, and is
> organization-prefixed so a mis-scoped read is visible in logs.
>
> Alembic does not autogenerate CHECK constraints, but does emit table-level
> ones for new tables — the status and kind constraints are real, and
> `tests/integration/test_generation.py::TestDatabaseConstraints` proves they
> reject bad values.
>
> Applied as `migrations/versions/0006_prompt_and_generation.py`; verified to
> run clean, to downgrade, and `alembic check` reports no drift.

## Migration 007 — creative evaluation and selection (Milestone 7) — **APPLIED**

> Two tables, and the two that are deliberately absent are as much of the design.
>
> **No `evaluation_jobs` table.** An evaluation *is* the unit of work, so its
> status lives on `creative_evaluations` itself: `PENDING -> RUNNING ->
> COMPLETED | FAILED`, with `payload` null until it finishes and `error` set
> instead when it does not. A second table pointing at this one would add a join
> and a way for the two to disagree about the same fact.
>
> **No rankings table.** A ranking is a pure function of the stored evaluations
> — overall score, then brand alignment, then campaign fit, then asset id — so
> persisting one would create a second source of truth free to fall out of step
> with the evaluations it summarises. It is computed on read.
>
> `creative_evaluations` is unique on `(generated_asset_id, evaluator_version)`.
> Re-running the same evaluator updates in place; a future `v2` writes a row
> *beside* `v1` rather than over it — which is the whole point of recording a
> version, since results from different criteria must never be silently compared
> as though they were equivalent.
>
> `overall_score` and `disposition` are denormalised out of the payload so
> ranking and filtering never parse JSON. They are written only together with
> the payload that produced them, and a CHECK keeps the score within 0-100.
>
> `specification_id` / `specification_version` record the plan the *asset* was
> generated from. An asset is always judged against the plan it was actually
> given, never one approved afterwards — after a Milestone 5 revision, "latest"
> would be the wrong plan.
>
> `creative_selections` is append-only: a change of mind adds a row and the
> current selection is the most recent, so "what did they pick first, and when
> did they change it?" stays answerable. `evaluation_id` is nullable on purpose
> — a human may overrule the ranking entirely, and the product must let them.
>
> Applied as `migrations/versions/0007_creative_evaluation.py`; verified to run
> clean, to downgrade, and `alembic check` reports no drift.

## Migration 008 — Brand Guardian and revision (Milestone 8) — **APPLIED**

> Two tables.
>
> `brand_guardian_results` mirrors `creative_evaluations` deliberately: the
> check is the unit of work, so its status lives on it rather than in a separate
> jobs table that could disagree. `status` says whether the check *ran*;
> `verdict` says what it *found*. A `NEEDS_REVISION` verdict is a completed
> check, not a failure, and a failed check leaves `verdict` null — an outage
> must never read as brand approval. Unique on
> `(generated_asset_id, guardian_version)`.
>
> `specification_revisions` is **not** a duplicate of Milestone 5's
> `creative_revisions`. That table records revisions of a *direction set*, and
> its `from_version`/`to_version` count direction-set versions. This one records
> revisions of a *Creative Specification*. The same pattern applied to a
> different artefact is not the same table, and sharing the columns would put
> two unrelated version spaces behind one name.
>
> **History is append-only and versions are never mutated.** `from_version`
> always points at a specification that still exists and still says what it
> said, so the assets generated from it keep pointing at something true.
> `to_version` is null until the human approves the delta at gate 1.
>
> `source_asset_id`, `evaluation_id` and `guardian_id` are `SET NULL` on delete:
> they record what was on the table when the human asked, which is provenance
> rather than a dependency. A revision stays meaningful after the asset that
> prompted it is gone.
>
> `user_feedback` is a column, not a log line — the human's own words are a
> first-class revision input.
>
> Applied as `migrations/versions/0008_guardian_and_revision.py`; verified to
> run clean, to downgrade, and `alembic check` reports no drift.

## Migration 009 — final composition (Milestone 9) — **APPLIED**

> Two tables, both append-only by version.
>
> `layout_specs` holds the `LayoutSpec` that *produces* a final asset — the
> source of truth for composition. Unique on `(campaign_id, channel, version)`.
> An accepted edit inserts a new version; no row is ever updated in place, so a
> layout that rendered a delivered asset keeps rendering exactly that.
>
> `final_assets` is one rendered deliverable. `kind` is constrained to
> `FINAL_BRANDED_ASSET` — a `generated_assets` row is a `VISUAL_PLATE` and
> nothing upstream may claim the other label (ADR-006). Unique on
> `(campaign_id, channel, version)`.
>
> **`layout_snapshot` is the point of the table.** The layout is carried inline
> as JSONB as well as by `layout_spec_id`: the id says which working document
> the asset came from, the snapshot says what it actually rendered. Without it,
> editing a layout would silently change what an already-exported file claims
> to be.
>
> Provenance is columnar because it is queried and must not be optional:
> `source_asset_id` (the plate), `specification_version` (the approved plan),
> `layout_version`, `renderer_version`, plus `width`, `height`, `mime_type` and
> `bytes`. A file with no answer to "what produced this?" is not a deliverable.
>
> `layout_spec_id` and `source_asset_id` are `SET NULL` on delete — they are
> provenance, not dependencies, and the snapshot already holds the recipe. An
> exported asset stays valid after the working layout or the plate is gone.
>
> `storage_key` is generated, never derived from user input:
> `org-{org}/campaign-{campaign}/final/{channel}-v{version}-{uuid}.{ext}`.
>
> Applied as `migrations/versions/0009_final_composition.py`; verified to run
> clean, to downgrade, and `alembic check` reports no drift.

## Migration 003 sketch — the fuller workflow (Milestones 3–5)

```sql
create table campaigns (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  project_id uuid not null references projects(id) on delete cascade,
  brand_profile_id uuid references brand_profiles(id),
  title text not null,
  status text not null default 'DRAFT'
    check (status in ('DRAFT','INTERVIEWING','STRATEGY','AWAITING_APPROVAL',
                      'GENERATING','EVALUATING','REVISING','COMPLETED','FAILED','CANCELLED')),
  thread_id text not null unique,        -- LangGraph thread; = campaign id as text
  created_by uuid references users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on campaigns (project_id, status);

create table campaign_runs (             -- one graph execution
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  status text not null default 'PENDING'
    check (status in ('PENDING','RUNNING','WAITING_HUMAN','COMPLETED','FAILED','CANCELLED')),
  current_node text,
  node_history jsonb not null default '[]',   -- [{node, status, ms, at}] -> progress UI
  error jsonb,
  iteration_count int not null default 0,
  started_at timestamptz, finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index on campaign_runs (campaign_id, created_at desc);

create table chat_messages (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  role text not null check (role in ('user','assistant','system')),
  content text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index on chat_messages (campaign_id, created_at);

create table campaign_briefs (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  version int not null default 1,
  payload jsonb not null,            -- domain.campaign.CampaignBrief
  schema_version int not null default 1,
  created_at timestamptz not null default now(),
  unique (campaign_id, version)
);

create table campaign_references (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  storage_key text not null,
  mime_type text not null, bytes bigint,
  analysis jsonb,                    -- domain.reference.ReferenceAnalysis
  status text not null default 'PENDING'
    check (status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
  error text,
  created_at timestamptz not null default now()
);

create table creative_directions (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  brief_id uuid references campaign_briefs(id),
  ordinal int not null,              -- 1..3
  title text not null,               -- promoted for list views
  is_recommended boolean not null default false,
  payload jsonb not null,            -- domain.creative.CreativeDirection
  created_at timestamptz not null default now(),
  unique (campaign_id, brief_id, ordinal)
);

create table creative_specifications (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  direction_id uuid references creative_directions(id),
  version int not null default 1,
  payload jsonb not null,            -- domain.creative.CreativeSpecification
  created_at timestamptz not null default now(),
  unique (campaign_id, version)
);

create table prompts (
  id uuid primary key default gen_random_uuid(),
  specification_id uuid not null references creative_specifications(id) on delete cascade,
  provider text not null,            -- 'gemini' | 'leonardo' | 'mock'
  model text not null,
  kind text not null check (kind in ('master','model')),
  text text not null,
  negative_text text,
  parameters jsonb not null default '{}',
  edited_by_user boolean not null default false,
  created_at timestamptz not null default now()
);

create table approvals (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  gate text not null check (gate in ('strategy','prompt','final')),
  decision text not null check (decision in ('APPROVE','REJECT','REQUEST_REVISION','EDIT','SELECT','REGENERATE','REQUEST_CHANGES')),
  target_id uuid,                    -- direction / spec / asset the decision refers to
  feedback text,
  decided_by uuid references users(id),
  created_at timestamptz not null default now()
);
create index on approvals (campaign_id, gate, created_at desc);
```

## Migration 004 — generation, evaluation, output (Milestones 6–9)

```sql
create table generation_jobs (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  prompt_id uuid not null references prompts(id),
  provider text not null, model text not null,
  status text not null default 'PENDING'
    check (status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')),
  idempotency_key text unique,       -- retry-safe; never double-bills a provider
  attempt int not null default 1,
  error jsonb,
  provider_job_id text,
  started_at timestamptz, finished_at timestamptz,
  created_at timestamptz not null default now()
);
create index on generation_jobs (campaign_id, status);

create table generated_assets (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  generation_job_id uuid not null references generation_jobs(id) on delete cascade,
  storage_key text not null,
  mime_type text not null, width int, height int, bytes bigint,
  seed text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table evaluations (
  id uuid primary key default gen_random_uuid(),
  generated_asset_id uuid not null references generated_assets(id) on delete cascade,
  overall_score numeric(4,2) not null,       -- promoted for ranking
  payload jsonb not null,                    -- domain.evaluation.CreativeEvaluation
  evaluator_model text,
  created_at timestamptz not null default now()
);

create table brand_guardian_results (
  id uuid primary key default gen_random_uuid(),
  generated_asset_id uuid references generated_assets(id) on delete cascade,
  specification_id uuid references creative_specifications(id) on delete cascade,
  stage text not null check (stage in ('precheck','asset')),
  verdict text not null check (verdict in ('PASS','NEEDS_REVISION','UNKNOWN')),
  payload jsonb not null,                    -- violations + rationale
  created_at timestamptz not null default now(),
  check (generated_asset_id is not null or specification_id is not null)
);

create table revisions (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  iteration int not null,
  from_specification_id uuid references creative_specifications(id),
  to_specification_id uuid references creative_specifications(id),
  user_feedback text,
  delta jsonb not null,              -- {keep:[...], change:{field: reason}}
  created_at timestamptz not null default now()
);

create table final_assets (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  source_asset_id uuid references generated_assets(id),
  channel text not null,             -- instagram_post | story | linkedin | banner | print_a3 ...
  width int not null, height int not null,
  layout_spec jsonb not null,        -- domain.layout.LayoutSpec, inline: the exact
                                     -- recipe that produced this file. Editing the
                                     -- design later must not retroactively change
                                     -- what an exported asset claims to be.
  storage_key text not null,
  created_at timestamptz not null default now()
);
create index on final_assets (campaign_id, channel);
```

## LangGraph tables

**Alembic must not touch these tables.** `migrations/env.py` excludes them via
`include_name` and `include_object`: autogenerate treats a table absent from
our metadata as an orphan and proposes `drop_table("checkpoints")`, which would
delete every paused campaign conversation. `tests/integration/test_migration_matches_models.py`
asserts the exclusion is still in place.

`setup()` also issues `CREATE INDEX CONCURRENTLY`, which cannot run inside a
transaction and waits for every open transaction on the database. It therefore
runs once at application startup — calling it inside a request deadlocks that
request against its own session.

`AsyncPostgresSaver.setup()` creates and owns four tables — `checkpoints`,
`checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations` — in the
**`public` schema, alongside the application tables**.

An earlier draft of this document claimed they land in a separate `langgraph`
schema. The R-2 spike disproved that (`docs/R2_CHECKPOINT_SPIKE.md`); the saver
takes no schema argument in langgraph-checkpoint-postgres 3.1.2. The separation
in ADR-004 is therefore logical, not physical: we neither model, migrate nor
query these tables, and Alembic must never be pointed at them. Execution state
lives there; product state lives in the tables above.

Everything LangGraph writes there is deserialized through the allowlist in
`app/graph/serde.py` under `LANGGRAPH_STRICT_MSGPACK=true`, so a checkpoint row
can only reconstruct types we have declared.

## Entity coverage

Every entity named in the product brief is accounted for:
`users` `organizations` `memberships` `projects` `brand_profiles` `brand_assets`
`brand_documents` (+`brand_chunks`) `campaigns` `chat_messages`(=chat sessions,
keyed by campaign) `campaign_briefs` (embeds `campaign_inputs` and
`creative_preferences` as validated sub-objects) `campaign_references`
(+ its `analysis`) `creative_directions` `creative_specifications` `prompts`
`generation_jobs` `generated_assets` `evaluations` `brand_guardian_results`
`approvals` `revisions` `final_assets` — plus `campaign_runs` for observability.

Three brief-level entities were folded rather than given tables:
`campaign_inputs` and `creative_preferences` are always read with their brief,
and `chat_sessions` is 1:1 with a campaign. Splitting them would add joins and
no capability. This is recorded here so the decision is visible, per rule 7.

## Change policy

No schema change without (a) an Alembic migration, (b) an update to this file,
and (c) a bump of `schema_version` on any affected `payload` column.
