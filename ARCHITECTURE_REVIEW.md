# ARCHITECTURE_REVIEW.md

Formal review of the Milestone 0 repository against the original project
context. Conducted 2026-09-11, before any Milestone 1 implementation.

Method: every claim below was checked against the actual files, not against
memory of writing them. Bugs marked **verified** were reproduced by executing
the code.

---

## 1. Overall assessment

**Architecture status: READY WITH FIXES.**

The spine is correct and worth keeping: specification-over-prompt, a single
typed state, contracts enforced by tests, providers behind Protocols, and
deterministic brand composition. Nothing in the product chain is structurally
blocked, and the layering has no cycles.

The review found **9 defects** — one of which crashes at runtime, three of
which silently lose user data or corrupt loop budgets, and five of which are
specification contradictions. All are cheap now and expensive after Milestone 4.
All nine are fixed in this pass.

The single largest risk is **not** architectural. It is that a 21-node graph
across 10 milestones does not fit a 9–11 day build. Section 6 cuts it to size.

### Product coverage

| Stage | Status | Where |
|---|---|---|
| Brand | **Full** | `BrandProfile`, `brand_profiles`, `load_brand_brain` |
| Campaign | **Full** | `campaigns`, `campaign_runs` |
| AI Interview | **Full** | `campaign_interviewer`, `CampaignInputs.is_sufficient()`, interrupt per turn |
| Campaign Specification | **Full** (renamed) | `CampaignBrief` — see Contradiction C-5 |
| Reference Intelligence | **Full** | `reference_intelligence`, `ReferenceAnalysis`, `AggregateReferenceStyle` |
| Market / Regional Intelligence | **Partial** | schemas + node exist; live web search is deferred (`SEARCH_PROVIDER=none`), so output is model knowledge only |
| Creative Directions | **Full** | `creative_director`, 3× `CreativeDirection` + `Recommendation` |
| Human Approval | **Full** | 3 gates, `interrupt()`, `ApprovalDecision` validated per gate, `approvals` table |
| Creative Specification | **Full** | `CreativeSpecification` with `locked_fields` |
| Prompt Compiler | **Full** | `prompt_compiler`, `MasterPrompt` → `ModelPrompt` per adapter |
| Multi-model Generation | **Partial** | router + adapters + fallback designed; only mock is committed for the demo, Gemini second, Leonardo deferred (§6) |
| Creative Evaluation | **Full** | 9 weighted criteria, `CreativeEvaluation.overall_score` |
| Brand Guardian | **Full** | separate verdict model, `precheck` + `asset` stages, `UNKNOWN` never means pass |
| Human Final Selection | **Full** | gate 3, ranking, side-by-side comparison specified |
| Revision Loop | **Full** | `RevisionDelta` KEEP/CHANGE, validator forbids a field being both |
| Final Asset | **Full** | `LayoutSpec` + Pillow, deterministic |
| Export | **Partial** | 7 channels defined; 3 committed, print A3/A4 deferred (§6) |

**Intentionally deferred, recorded so it is a decision and not an omission:**
live web search, Leonardo, references as Brand Brain RAG sources, print sizes,
Supabase storage, Sentry, Playwright, drag-and-drop editing.

**One deliberate divergence from the chain as written.** The requested order is
`Campaign Specification → Reference Intelligence`. The graph runs reference and
market intelligence *before* `campaign_brief_builder`. This is intentional: a
brief written without knowing the reference style has to be rewritten once the
references are analysed. Both intelligence nodes are degrade-safe, so the brief
is still produced when they fail.

---

## 2. Strengths

1. **Specification-over-prompt is real, not aspirational.** No state field, no
   table and no node treats a prompt string as authoritative. `ModelPrompt`
   hangs off `specification_id` and is regenerable; `edited_by_user` records a
   human override without promoting it to source of truth.
2. **The contract test already earns its keep.** It caught a defect during
   Milestone 0 (`creative_ranking` declared as degrading with no way to record
   a degradation) and caught three more in this review.
3. **Failure is modelled, not caught ad hoc.** `FailureMode` is part of each
   contract, `UNKNOWN` is a distinct guardian verdict, partial generation
   success is a first-class outcome, and `ExportManifest.failed` exists.
4. **Provider isolation holds.** `registry.py` is the only module naming a
   vendor; imports are lazy, so `mock` never loads an SDK.
5. **Evaluation and governance are correctly separated.** Score and veto are
   different models with different failure semantics.
6. **The environment was measured.** No Docker requirement, pgvector confirmed
   present, versions pinned to what actually resolved on Python 3.13.

---

## 3. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R-1 | **10 milestones, 21 nodes, 9–11 days.** The plan is ~2× the available time. | **High** | §6 and §9: cut to 13 nodes and 6 working days of scope, with named deferrals |
| R-2 | State is proven JSON-round-trippable but **not** proven round-trippable through LangGraph's own serializer | High | test against `AsyncPostgresSaver` on day 1 of M4, before any node is written |
| R-3 | Three "distinct" directions come back near-identical | Medium | `distinctness_note` exists; add a similarity check at M5 |
| R-4 | Gemini embedding dimension. `gemini-embedding-001` returns **3072** by default; the column is `vector(1536)` | Medium | pass `output_dimensionality=1536`; startup assertion already specified |
| R-5 | Browser preview and server renderer drift | Medium | server render authoritative; parity test at M9 |
| R-6 | Interview never terminates and burns the demo | Medium | `is_sufficient()` + turn cap (now a separate counter, F-2) |
| R-7 | Print A3 is a 17-megapixel Pillow render | Low | deferred (§6) |

---

## 4. Missing pieces

| # | Gap | Needed by |
|---|---|---|
| M-1 | **Nowhere persists `campaign_inputs` during the interview.** They live only in `campaign_briefs`, which does not exist until the interview ends. The checkpointer holds them, but ADR-004 forbids the UI reading execution state — so the "known facts" panel has no source. | **Milestone 3** |
| M-2 | `CreativePreferences` (Style Explorer output) has no persistence before a brief exists. Same root cause as M-1. | Milestone 3 |
| M-3 | No table or column records **which run** answered a gate; `approvals` has no `run_id`. Audit trail is incomplete across re-runs. | Milestone 5 |
| M-4 | Nothing enforces `RevisionDelta.keep ⊇ CreativeSpecification.locked_fields`. A revision could legally change a locked field. | Milestone 8 |
| M-5 | Brand Brain does not ingest **uploaded references** or **previous campaigns** as retrievable sources, though `brand_documents.source_type` allows `'campaign'`. | Deferred (§8) |
| M-6 | `brand_profiles` carries both `organization_id` and a nullable `project_id` — the cardinality (one brand per org, or per project?) is undecided. | Milestone 2 |

M-1 and M-2 share one cheap fix: a `campaigns.draft_inputs jsonb` column
written at each interview turn. Recorded here; **not** applied, because it is a
Milestone 3 schema decision and migration 001 should not carry speculative
columns.

---

## 5. Contradictions

All verified against the files.

| # | Contradiction | Evidence |
|---|---|---|
| **C-1** | `reference_analysis` is annotated `upsert_by_id`, but `ReferenceAnalysis` has **no `id` field**. Reproduced: `AttributeError: 'ReferenceAnalysis' object has no attribute 'id'`. This would crash `reference_intelligence` on its first write. | verified by execution |
| **C-2** | `iteration_count` is written by **both** `campaign_interviewer` and `revision_planner`, and both loops are guarded by it. An 8-turn interview exhausts the revision budget before the first revision. | `writers_of("iteration_count")` |
| **C-3** | Gate 2 accepts `edits` (API_SPEC) and routes `EDIT → prompt_compiler`, but `prompt_compiler` reads only `selected_direction, campaign_brief, brand, revision_delta`. It cannot see the edits and would overwrite them. **Silent data loss.** | contracts.py:163 vs GRAPH_SPEC:113 |
| **C-4** | `brand_guardian_precheck` writes `model_prompts`. A detector that also rewrites its subject conflates detection with correction — and the routing table *already* sends failures back to `prompt_compiler` to fix them. | contracts + GRAPH_SPEC §3 |
| **C-5** | The original brief's **"Campaign Specification"** (its stated single source of truth) appears nowhere in our docs. We named it `CampaignBrief`. The concept is implemented; the name is not traceable. | `grep` returns nothing |
| **C-6** | DATABASE_SCHEMA states "every tenant-scoped table carries `organization_id`". **7 of 23 tables do.** The other 16 are scoped by joining to `campaigns`/`projects`. | 23 tables, 7 matches |
| **C-7** | `FinalAsset.layout_spec_id: Id` (domain) vs `final_assets.layout_spec jsonb` (DDL). There is no `layout_specs` table for the id to point at. | layout.py:163 vs schema:320 |
| **C-8** | TESTING.md documents `MOCK_FAILURE_MODE=timeout\|malformed\|rate_limit`. No such setting exists in `Settings` or `.env.example`. | grep |
| **C-9** | `replace()` reducer is defined and tested but **used by no state field**; `successful_assets()` returns every asset, successful or not, so its name misleads. | state.py:146 |

---

## 6. Overengineering

Classified against a **9–11 day** delivery, which is the binding constraint.

| Component | Verdict | Reasoning |
|---|---|---|
| Single typed `CampaignState` | **KEEP** | cheap, and it is what makes resume and revision tractable |
| Contract registry + enforcement test | **KEEP** | already caught 4 real defects; ~150 lines |
| 5 provider Protocols | **KEEP** | the swap is a product requirement, and mocks depend on it |
| Postgres checkpointer + `interrupt()` | **KEEP** | the gates are the product; in-memory loses a demo to one reload |
| Deterministic Pillow composition | **KEEP** | highest value per hour in the build: it is what makes output look corporate, and it turns N channels into a loop |
| `MasterPrompt` intermediate | **KEEP** | it is one string; it is what keeps two providers on one idea |
| `campaign_runs.node_history` | **KEEP** | drives the progress stepper — very high demo value, ~20 lines |
| pgvector Brand Brain | **KEEP, timeboxed 1 day** | genuine differentiator, and pgvector is already installed. If it slips, the structured `BrandProfile` alone still feeds every node |
| **21-node graph** | **SIMPLIFY → 13 nodes** | build `load_project, load_brand_brain, campaign_interviewer, reference_intelligence, campaign_brief_builder, creative_director, human_strategy_approval, prompt_compiler, human_prompt_approval, generation_router, image_generation, creative_evaluator, brand_guardian, creative_ranking, human_final_selection, final_asset_builder, export, terminal_failure`; defer `market_intelligence`, `brand_guardian_precheck`, `revision_planner` to the last two days. All three are degrade-safe or optional edges, so the graph is correct without them |
| 7 export channels | **SIMPLIFY → 3** | Instagram post, story, LinkedIn. Print A3/A4 is a 17 MP render for no demo value |
| `brand_guardian_precheck` auto-fix loop | **SIMPLIFY** | run the precheck, show warnings at Gate 2, drop the automatic re-compile attempt. Removes `precheck_attempts` branching |
| Market intelligence + `SearchProvider` | **SIMPLIFY** | keep the node and schemas, drop live web search. Regional context from model knowledge is enough and has no API dependency |
| Final editor | **SIMPLIFY** | edit text, CTA, logo choice and element visibility on the `LayoutSpec`. No drag-and-drop canvas |
| Leonardo provider | **DEFER** | the router, adapters and fallback already exist; adding it later is one adapter. Mock + Gemini demonstrates multi-model |
| Supabase Storage adapter | **DEFER** | local filesystem works locally and on a Railway volume |
| Sentry | **DEFER** | structlog + `campaign_runs.error` covers the demo |
| Playwright | **DEFER** | backend e2e covers the journey; frontend E2E is a week-2 luxury |
| References as RAG sources | **DEFER** | reference *analysis* already reaches the director directly |
| Role-based authorization | **DEFER** | roles stay in the schema, enforcement stays out, exactly as the brief allows |
| `campaigns.thread_id` column | **REMOVE** | it is `campaigns.id` rendered as text. Derive it |
| `replace()` reducer | **REMOVE** | unused (C-9) |

Nothing in the *architecture* is overbuilt. The overbuild is entirely in the
**delivery plan**, and §9 fixes that.

---

## 7. Required fixes before Milestone 1

Applied in this pass. Each is a contract, schema or config change with no
feature implementation.

| # | Fix | Addresses |
|---|---|---|
| F-1 | `upsert_by_id` takes an explicit identity key; `reference_analysis` uses `reference_id`. New test asserts **every** upsert-annotated field's item type actually has its key — so this class of bug cannot recur | C-1 |
| F-2 | Split the loop counters: `interview_turn_count` (interviewer) and `iteration_count` (revision only). Test asserts each has exactly one writer | C-2 |
| F-3 | `prompt_compiler` now reads `creative_specification` and `approval_states`, with the documented rule that a field carrying a user edit is never overwritten by a recompile | C-3 |
| F-4 | `brand_guardian_precheck` no longer writes `model_prompts`. It reports; `prompt_compiler` fixes | C-4 |
| F-5 | Documented that `CampaignBrief` **is** the brief's "Campaign Specification", in ARCHITECTURE and PRODUCT_SPEC, so the original vocabulary stays traceable | C-5 |
| F-6 | Corrected the tenancy convention in DATABASE_SCHEMA to state the truth: root tables carry `organization_id`; descendants are scoped by join, enforced in the repository layer | C-6 |
| F-7 | `FinalAsset` carries the `LayoutSpec` inline, matching the DDL. No phantom `layout_specs` table | C-7 |
| F-8 | `MOCK_FAILURE_MODE` added to `Settings` and `.env.example` | C-8 |
| F-9 | Removed `replace()`; renamed `successful_assets()` → `assets_for_review()` | C-9 |

**Not fixed, deliberately:** M-1/M-2 (`campaigns.draft_inputs`) is a Milestone 3
migration and must not be speculatively added to 001. M-3, M-4, M-6 belong to
the milestones that build them. All are logged above.

---

## 8. Deferred features

Confirmed out of scope for the 9–11 day build, in the order they should return:

1. Leonardo (second live image provider) — one adapter; the router is ready
2. Live web search for market intelligence
3. Print A3/A4 export
4. Drag-and-drop layout editing
5. References and past campaigns as Brand Brain RAG sources
6. Supabase Auth + Storage adapters
7. Sentry, Playwright
8. Role enforcement, preference learning, publishing, analytics (Level 4)

None of these is on the critical path to the target demo.

---

## 9. Recommended Milestone 1 boundary

**In scope**

- Migration 001 only: `organizations, users, memberships, projects` (+ `pgcrypto`, `citext`, `vector`)
- Alembic wired and running against local Postgres
- `Principal` resolution via the dev-stub auth adapter
- Repository base class that takes `organization_id` and applies it to **every** query — the single mechanism that makes C-6's join-scoping safe
- `LocalStorageProvider` (the first real provider, and the one the demo depends on)
- FastAPI app: error envelope, request ids, structured logging, `GET /v1/me`, org/project CRUD, `/health`
- Next.js shell: app layout, org switcher, project list, project create — with real loading, empty and error states
- Integration tests against a real `campaign_os_test` database, including a
  parametrized cross-organization isolation test

**Explicitly out of scope for M1**

Brands, documents, embeddings, campaigns, the graph, any LLM or image call,
uploads beyond the storage provider itself, roles.

**Exit criteria**

`uv run pytest` green including the new integration layer · a cross-org read
returns 404 · the shell renders a created project end to end · migration 001
runs clean from empty.

**Suggested 11-day shape** (M = milestone in ROADMAP.md)

| Days | Work |
|---|---|
| 1–2 | M1 + M2 (brand profile & assets; RAG timeboxed to day 2) |
| 3–4 | M3 + M4 — graph, checkpointer, first interrupt. **Resume-after-restart test on day 3** |
| 5–6 | M5 + M6 — directions, gate 1, compiler, gate 2, mock then Gemini generation |
| 7–8 | M7 — evaluator, guardian, ranking, gate 3 |
| 9 | M9 lite — final asset + 3 channel exports |
| 10 | M8 — revision loop (last, because the demo survives without it) |
| 11 | Seed data, demo rehearsal, buffer |

Revision loop is scheduled late on purpose: it is the most impressive feature
and the most expendable one. Everything before it is a complete story.

---

## Verification record

**Architecture status: READY WITH FIXES** — all nine fixes applied and verified;
no blocker remains before Milestone 1.

### Files changed

| File | Change |
|---|---|
| `backend/app/graph/reducers.py` | `upsert_on(key)` factory replaces the hardcoded `.id` assumption; `upsert_by_id = upsert_on("id")` kept for the common case; dead `replace()` removed (F-1, F-9) |
| `backend/app/graph/state.py` | `reference_analysis` keyed on `reference_id`; added `interview_turn_count` + `can_ask_another_question()`; `successful_assets()` → `assets_for_review()`; helpers compare enums, not strings (F-1, F-2, F-9) |
| `backend/app/graph/contracts.py` | interviewer owns `interview_turn_count` only; `prompt_compiler` reads `creative_specification`, `approval_states`, `guardian_precheck` with the edit-preservation rule documented; `brand_guardian_precheck` no longer writes `model_prompts` (F-2, F-3, F-4) |
| `backend/app/domain/layout.py` | `FinalAsset.layout_spec_id` → `layout_spec: LayoutSpec`, matching the DDL (F-7) |
| `backend/app/config.py` | added `mock_failure_mode` (validated) and `max_interview_turns` (F-2, F-8) |
| `backend/tests/test_state.py` | C-1 guard walking every upsert field, C-2 budget-independence test, `merge_dict` immutability test; `replace()` test removed |
| `backend/tests/test_node_contracts.py` | single-owner test per loop budget, detector-does-not-rewrite test, compiler-sees-edits test |
| `.env.example` | `MOCK_FAILURE_MODE`, `MAX_INTERVIEW_TURNS` (F-2, F-8) |
| `docs/ARCHITECTURE.md` | "Campaign Specification" ≡ `CampaignBrief` naming note (F-5) |
| `docs/PRODUCT_SPEC.md` | same mapping in the journey diagram (F-5) |
| `docs/GRAPH_SPEC.md` | separate loop budgets in routing; pre-check reports / compiler repairs; recompile-never-overwrites-an-edit rule; node table regenerated from the contracts |
| `docs/DATABASE_SCHEMA.md` | tenancy convention corrected to root-tables-carry-org / descendants-scoped-by-join, with the repository base class named as the single enforcement point (F-6) |
| `ARCHITECTURE_REVIEW.md` | new |

No node, route, migration or component was implemented. Every change is to a
contract, a schema, configuration, a test or a document.

### Tests run

```
ruff check .          All checks passed!
ruff format --check   34 files already formatted
mypy app              Success: no issues found in 29 source files
pytest tests/ -q      93 passed, 1 skipped in 0.06s
```

Test count moved 85 → 93: seven added (three C-1 upsert guards, C-2 budget
independence, C-3 compiler-reads-edits, C-4 detector-does-not-rewrite,
`merge_dict` immutability), one removed with `replace()`, one net rename.
The single skip is the runtime node-write check, which activates at Milestone 4.

Both runtime defects were also confirmed fixed by direct execution: every
upsert-annotated field's key now resolves on its item type, the previously
crashing `ReferenceAnalysis` upsert succeeds, and an exhausted interview budget
leaves the revision budget untouched.

### Recommended next action

Begin **Milestone 1** at the boundary in §9 — migration 001, the
organization-scoped repository base class, dev-stub auth, `LocalStorageProvider`,
`GET /v1/me` plus org/project CRUD, and the Next.js shell — and adopt the
11-day shape, which requires accepting the deferrals in §8.

Before writing a single node in Milestone 4, run the R-2 spike first:
round-trip a populated `CampaignState` through `AsyncPostgresSaver` and resume
it in a fresh process. Today's tests prove Pydantic JSON round-trips, which is
not the same guarantee.
