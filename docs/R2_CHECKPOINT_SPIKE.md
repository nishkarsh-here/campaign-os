# R-2 — LangGraph Postgres checkpointer round-trip

**Result: PASS.** Verified 2026-09-11 against PostgreSQL 18.3, LangGraph 1.2.11,
langgraph-checkpoint-postgres 3.1.2, Python 3.13.9.

Permanent test: `backend/tests/integration/test_r2_checkpoint_resume.py`
Runner (executed as two separate OS processes): `backend/tests/integration/r2_resume_runner.py`

## Why this was worth proving first

Every human approval gate in `docs/GRAPH_SPEC.md` assumes a paused graph can be
resumed later, in a different process. Milestones 4–8 are built on that. The
Milestone 0 tests only proved `CampaignState` round-trips through *Pydantic*
JSON, which is a different guarantee entirely — LangGraph checkpoints with
msgpack, not `model_dump_json`.

## Method

Two phases, each a separate `python -m` process. Nothing is shared between them
except the Postgres checkpoint — not the saver, not the compiled graph, not the
interpreter. An in-process test would have proved almost nothing, since a
cached object graph would carry the state for free.

- **Phase A** — build a 3-node graph over the real `CampaignState`, populate a
  deep slice of it (nested models, enums, datetimes, both reducer kinds), run
  into `interrupt()`, exit.
- **Phase B** — new process. Given only a `thread_id`, recover the pending gate,
  resume with `Command(resume=...)`, run to completion.

## What was verified

| # | Requirement | Evidence |
|---|---|---|
| 1 | Starts in one process | phase A exits after the interrupt |
| 2 | Executes through an interrupt/checkpoint boundary | `interrupted: true`, `next_nodes: ["gate"]` |
| 3 | Persists through `AsyncPostgresSaver` | real `campaign_os_test` database |
| 4 | Terminated and recreated | separate `subprocess.run` calls |
| 5 | Resumes from the persisted checkpoint | phase B reports `resumed_from_pending_node: ["gate"]` |
| 6 | Preserves state | brand, brief, conversation, jobs, errors identical |
| 7 | Continues without corruption | runs to `COMPLETED`; decision recorded |

Two results matter more than the rest:

**Models rehydrate as models, not dicts.** `state.brand` comes back as a real
`BrandProfile`, and `brand.primary_color().hex` returns `#1F2933` in the fresh
process. Had this returned a plain dict, every node calling a domain method
would have broken at Milestone 5, far from the cause.

**Reducers still behave with msgpack and Postgres in the path.** `conversation`
appended (1 → 2) rather than being replaced, and `generation_jobs` upserted —
one job, `PENDING` → `COMPLETED`, not two rows. Enums (`Channel`, `StyleFamily`,
`JobStatus`) and timezone-aware datetimes survived unchanged.

## Defect found and fixed

The first run passed, but LangGraph emitted:

```
Deserializing unregistered type app.domain.common.Channel from checkpoint.
This will be blocked in a future version. Set LANGGRAPH_STRICT_MSGPACK=true
to block now, or add to allowed_msgpack_modules to allow explicitly.
```

Left alone this is a latent break: a LangGraph upgrade would start refusing our
own domain types and disable resume — the one mechanism every approval gate
depends on — with no code change on our side to explain it. The permissive
default is also a security posture we did not choose: a deserializer that will
instantiate any named type lets anyone who can write to the checkpoint table
choose what gets constructed.

**Fix:** `backend/app/graph/serde.py` builds a `JsonPlusSerializer` with an
allowlist derived from `app.domain.__all__` plus `CampaignState`, and
`checkpointer_kwargs()` is the single supported way to construct a
checkpointer. The allowlist is *derived*, not hand-listed, because a
hand-written list would rot the first time someone adds a field of a new type.

> **Correction (2026-09-12, M1_SECURITY_AUDIT finding A-2).** As first written,
> this fix did not work. `build_serde()` called
> `JsonPlusSerializer().with_msgpack_allowlist(...)`, and that method
> short-circuits on a permissive base — a bare `JsonPlusSerializer()` starts at
> allow-everything unless `LANGGRAPH_STRICT_MSGPACK` is in `os.environ`, so the
> declared types were silently discarded. `LANGGRAPH_STRICT_MSGPACK=true` in
> `backend/.env` did not help either: pydantic-settings reads that file into
> `Settings`, never into `os.environ`. The control this document described as
> active was inert in the running server. The allowlist is now passed to the
> **constructor**, which makes it unconditional, and
> `backend/tests/test_checkpoint_serde.py` asserts it holds with the
> environment variable deleted.

The integration test asserts the warning is absent from stderr, so a future
domain type that escapes the allowlist fails the build.

## Limits of this result

- One interrupt, one resume, one thread. Concurrent writers to the same thread
  are not covered; nothing in the design needs them yet.
- The graph used here is a purpose-built 3-node stand-in, not the product
  graph. This proves the *persistence mechanism*, not the product's nodes.
- Checkpointer tables are created by `AsyncPostgresSaver.setup()` in the
  default schema, **not** in a separate `langgraph` schema as
  `docs/DATABASE_SCHEMA.md` speculated. That claim has been corrected: the
  tables are `checkpoints`, `checkpoint_writes`, `checkpoint_blobs` and
  `checkpoint_migrations`, alongside the application tables. They remain
  LangGraph's to own — we neither model nor query them.

## Consequence for the roadmap

Risk R-2 in `ARCHITECTURE_REVIEW.md` is closed. ADR-003 (Postgres checkpointer,
HITL via `interrupt()`) is confirmed by execution rather than by reading docs,
and Milestone 4 can proceed without a persistence spike of its own.
