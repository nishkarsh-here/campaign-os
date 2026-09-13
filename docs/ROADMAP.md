# ROADMAP.md

Built **vertically**: a thin path that runs end to end, then depth. At every
milestone the product is demonstrable. Each milestone lists its exit criteria —
these are the definition of done, not aspirations.

| # | Milestone | Exits when | Level |
|---|---|---|---|
| **0** | **Architecture + contracts** ✅ | isolated repo; 9 docs; `CampaignState`; domain schemas; node contracts; provider Protocols; DB entities; slice defined; schema tests pass | — |
| **1** | **Product shell + DB + auth** ✅ | migration 001 runs clean from empty and reverses; dev-stub auth resolves a Principal behind a replaceable `AuthProvider`; org-scoped repositories with a cross-tenant probe over every one; org/project CRUD; Next.js shell; `/v1/me` green; loading/empty/error states real | — |
| **2** | **Brand onboarding + Brand Brain** ✅ | brand CRUD; logo/asset upload validated by magic bytes; PDF and text ingest -> chunk -> embed -> pgvector; retrieval returns ranked chunks with provenance; Brand Brain page usable; AI facts stay proposals until a human accepts them | L1 |
| **3** | **Campaign discovery + specification** ✅ | interviewer asks only gap-filling questions, prioritises by impact, consults the Brand Brain before asking, and terminates; `CampaignInputs` validated; the CAMPAIGN SPECIFICATION is generated, editable, and confirmable; stated / inferred / not-applicable tracked per field | L1 |
| ~~4~~ | ~~LangGraph core~~ | **Delivered early, inside Milestone 3**: the graph is assembled with the Postgres checkpointer, the interview loop runs as real nodes, and `interrupt()`/resume is proved by integration tests that rebuild the saver and graph. What remains for a later milestone is the *rest* of the graph, not its machinery | L3 |
| **4** | **Reference intelligence + creative context** ✅ | campaign references analysed through the multimodal provider abstraction into typed style characteristics; deterministic weighted preference profile; `CreativeContext` assembles brand + specification + reference DNA + preferences for the Creative Director to consume | L2 |
| **5** | **Creative Director + human approval** ✅ | 3 directions checked distinct by deterministic overlap, not hoped to be; recommendation with readable reasons; two human gates (strategy, specification) on real interrupt/resume; approve/reject/revise all route correctly; confirmed campaign facts pinned through both model calls; every decision persisted | L1 |
| **6** | **Prompt Compiler + multi-model generation** ✅ | deterministic compilation of an approved `CreativeSpecification` into a typed `CanonicalPrompt`; per-provider prompt adapters; versioned prompts traceable to their source; explicit generation jobs per provider with partial success and retry; mock provider offline, Gemini adapter through the same Protocol; plate gallery | L1 |
| **7** | **Creative Evaluator + recommendation** ✅ | 10 typed dimensions scored 0-100 against the asset's *own* Creative Specification version, campaign and Brand Brain; overall score is a deterministic weighted mean and the disposition comes from published thresholds, never from the model; per-asset evaluation jobs with partial failure and retry; deterministic ranking with explicit tie-breaks; recommendation that declines to name a winner when nothing passed; human selection persisted. Brand Guardian moves to M8 | L1 |
| **8** | **Brand Guardian + revision loop** ✅ | guardian verdict computed from its own checks, with claim safety, brand restrictions and palette decided in code rather than asked of a model; natural-language feedback becomes an explicit KEEP/CHANGE/ADD/REMOVE delta shown before anything runs; two human gates; deterministic application produces the next specification version while the previous one stays byte-for-byte intact; regeneration and re-evaluation reuse M6/M7 unchanged | L1 |
| **9** | **Final brand composition + editor + export** ✅ | `LayoutSpec` is the source of truth and the PNG its output; deterministic Pillow renderer composes logo, headline, CTA, scrim and safe areas from approved brand and campaign data; geometry validated before a pixel is drawn, so a broken layout is reported rather than rendered; constrained editor that refuses with a typed sentence rather than silently dropping a change; channel variants as re-layouts off the existing `CHANNEL_DIMENSIONS`; PNG and JPEG export with full provenance; every edit a new layout version and every render a new asset, nothing overwritten | L1 |
| **10** | **Production polish + reliability + deployment** ✅ | one canonical demo campaign seeded by running the real services, resettable; enforced `DEMO_MODE` that refuses a live provider and says so in the UI; a campaign command centre that reads from the services rather than storing its own state; startup reconciliation so a restart mid-job becomes a visible retryable failure instead of a permanent spinner; provider-error redaction; deployment and demo runbooks; every setting documented and asserted against `Settings` | — |

| **11** | **Per-channel creative copy** ✅ | one optional `channel_copy` map on the Creative Specification and a single `copy_for` resolver; a channel may carry its own headline, subhead and call to action, and an absent override inherits the campaign's; overrides are approved at Gate 2, restricted to channels the Campaign Specification declares, scanned by the Brand Guardian, revisable one channel at a time, and refused in the composition editor exactly as the default copy is | L1 |

Second image provider (Leonardo) lands opportunistically after M6 — the router
and adapters already exist, so it is an adapter plus a config value. It is not
allowed to block M7.

## First vertical slice (Milestones 1–6)

The backbone that everything else hangs off:

```
brand -> campaign -> AI interview -> campaign brief -> 3 creative directions
      -> [Gate 1] -> creative specification -> prompt -> ONE image provider
      -> evaluation -> [Gate 3] final selection
```

Deliberately excluded from the slice, added immediately after: reference
analysis, market intelligence, Brand Guardian, second provider, revision loop,
editor, export. Each is degrade-safe (GRAPH_SPEC §2), so the slice runs correctly
without them and does not need rework to receive them.

**Slice acceptance:** with `IMAGE_PROVIDER=mock` and no network, a new user can
create a brand, run a campaign to a finished selected creative, and every step is
persisted, resumable and visible in the UI.

## Risk register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Live provider dies during the demo | graded presentation | mock providers are the default and are always tested; seeded demo campaign; router falls back |
| Three "distinct" directions come back samey | the core value prop is *choice* | distinctness constraint in the prompt, plus an automated similarity check that triggers one regeneration |
| Interviewer never stops asking | ruins the first impression | explicit sufficiency check against required brief fields + hard question cap |
| Image model cannot render brand text | corporate creatives look fake | ADR-006 — deterministic composition; never ask the model for text |
| LangGraph API churn | orchestration is load-bearing | pinned version; graph assembly isolated to `app/graph/build.py`; nodes are plain async functions, testable without LangGraph |
| pgvector dimension mismatch | silent retrieval garbage | dimension asserted against the provider at startup; migration required to change |
| Scope creep into Level 4 | nothing ships | the ladder is the contract; L4 items only after M10 |

## Deployment target

Frontend on Vercel. Backend on Railway or Render (Docker is absent locally, so
the image is built in CI, never required for development). Postgres: managed
instance or Supabase — same engine, DSN swap. Secrets only via environment.
