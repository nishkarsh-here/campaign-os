# TESTING.md

**Every test runs offline against mock providers.** No test may require a network
call, an API key, or credit. `conftest.py` forces `LLM_PROVIDER=mock`,
`IMAGE_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, `STORAGE_PROVIDER=local` and
fails the session if a real provider is selected under `APP_ENV=test`.

```bash
cd backend
uv run pytest                 # everything
uv run pytest -m unit         # fast
uv run pytest -m integration  # needs the test database
uv run pytest -m e2e          # the full campaign walk
```

## Layers

### Unit (`-m unit`) — no I/O
- **Domain schemas** — required fields, validators, enum bounds, round-trip
  `model_dump`/`model_validate`, rejection of malformed payloads.
- **State** — reducers append rather than replace; partial updates merge; state
  stays JSON-serializable (a checkpointing requirement, so it is asserted).
- **Node contracts** — `tests/test_node_contracts.py` walks `NODE_CONTRACTS` and
  every registered node and asserts: the node is declared, its declared reads and
  writes are real `CampaignState` fields, and (via an executed-node recorder)
  it writes nothing it did not declare. This is the mechanical enforcement of
  "each node has defined inputs and outputs".
- **Prompt compilation** — a fixed `CreativeSpecification` compiles to a
  deterministic prompt per adapter; snapshot-tested so prompt drift is visible in
  a diff and reviewed rather than discovered in an image.
- **Provider adapters** — Protocol conformance for every implementation; retry,
  timeout and error mapping against a fake transport.
- **Evaluator / Guardian** — scoring maths, ranking order, tie-breaks, and that a
  prohibited-claim violation always yields `NEEDS_REVISION`.
- **Revision delta** — KEEP fields are provably unchanged after applying a delta.
- **Layout renderer** — a `LayoutSpec` renders to expected dimensions with text
  inside safe areas; deterministic byte-identical output for identical input;
  text that cannot be made to fit raises rather than overflowing silently; a
  layout placing a logo the brand does not have refuses rather than inventing
  one.
- **Layout validation** — the default layout for every composable channel
  reports no issues at all, so the panel never cries wolf; a clipped logo or an
  out-of-safe-area CTA is blocking; a full-bleed scrim is not flagged, because
  the safe area governs content and a scrim is backdrop.

### Integration (`-m integration`) — real Postgres, mock providers
Runs against `campaign_os_test`, migrated fresh, each test in a rolled-back
transaction.
- repository CRUD **plus** the org-scope guarantee: a foreign-org id returns
  nothing, on every repository, as a parametrized test
- brand document ingest -> chunk -> embed -> retrieve, asserting relevance order
- graph execution to a gate, with a **new process/graph instance** resuming from
  the checkpoint — this is the property the demo depends on, so it is tested
  directly rather than assumed
- API contract tests per endpoint: happy path, validation failure, wrong org,
  gate conflict (409), idempotency replay
- final composition end to end: compose -> render -> edit -> re-render, asserting
  layout v1 is byte-identical afterwards, that final asset v1 still points at
  layout v1 and still has its own file, and that only the requested element
  changed. Every editor refusal is asserted as a typed error *and* as a `400`
  with a readable message, including the deliberate invalid-layout case
- provider failure injection: an image provider that always fails must produce
  `FAILED` jobs, a surviving run, and a visible reason

### End-to-end (`-m e2e`)
One test walks the target demo:

```
create org+project -> create brand -> ingest a brand doc -> create campaign
-> interview turns until complete -> brief -> 3 directions
-> approve direction (gate 1) -> spec + prompts -> approve (gate 2)
-> generate across two mock providers -> evaluate -> guardian -> rank
-> select (gate 3) -> final asset -> export 3 channel variants
```

Asserts at each step that persisted state matches graph state, that all three
gates actually paused, and that the run ends `COMPLETED` with real files on disk.
A second e2e variant exercises the revision loop and asserts KEEP fields survived.

Frontend E2E (Playwright) lands in Milestone 10 and drives the same journey
against a seeded backend.

## Fixtures

`tests/fixtures/` holds a seeded demo organization, a fictional brand with
guidelines, palette and logo, two reference images, and a canned campaign brief.
The same fixtures seed the demo database — the demo is a passing test, which is
what keeps it from rotting.

## Mock provider behaviour

Mocks are deterministic, not random: same input, same output, seeded by a hash of
the request. `MockImageProvider` composes a labelled placeholder plate at the
requested aspect ratio so downstream layout and export are exercised for real.
Mocks can be told to fail (`MOCK_FAILURE_MODE=timeout|malformed|rate_limit`) so
error paths are tested rather than hoped about.

## Bar

- Meaningful logic ships with tests, in the same change.
- Bug fixes ship with the test that would have caught them.
- `uv run pytest` must pass before any milestone is called done.
- Coverage is a signal, not a target; the e2e path and every error branch matter
  more than a percentage.
