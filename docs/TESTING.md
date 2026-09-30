# TESTING.md

**Every test runs offline against mock providers.** No test may require a network
call, an API key, or credit. `conftest.py` forces `LLM_PROVIDER=mock`,
`IMAGE_PROVIDER=mock`, `EMBEDDING_PROVIDER=mock`, `STORAGE_PROVIDER=local` and
fails the session if a real provider is selected under `APP_ENV=test`.

Two things in this repository deliberately reach an external service, and
neither runs by default:

- **`scripts/gemini_*_smoke_test.py`** — three hand-run scripts. Not tests,
  never collected by pytest. See [DEPLOYMENT §5](DEPLOYMENT.md#5-providers).
- **`tests/integration/test_gemini_image_live.py`** — marked `live`, and
  `pyproject.toml` sets `addopts = "-m 'not live'"`, so `uv run pytest`
  deselects it and CI can never come to depend on an external API or a valid
  card. It also skips itself when `GEMINI_API_KEY` is absent. Opting in is
  deliberate:

  ```bash
  GEMINI_API_KEY=… uv run pytest -m live
  ```

  It generates **exactly one image** — `MAX_SMOKE_TEST_IMAGES = 1`, asserted
  rather than assumed, because a suite that quietly produced a dozen is a way
  to lose money by running the tests twice.

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
- **Documents asserted against the code they describe.** Three now, each because
  the document had drifted and nothing failed: `.env.example` against `Settings`
  both ways (`test_config.py`), `docs/API_SPEC.md` against the OpenAPI schema
  both ways plus its error-code table against every emittable code
  (`test_api_spec_matches_routes.py`), and the environment block in
  `docs/DEPLOYMENT.md` §7 *executed* — `Settings` is built from it and every
  provider it names is constructed (`test_deployment_startup.py`). A prose claim
  that can be checked should be.
- **The authorization matrix** (`test_authz.py`) — every role against every
  capability, written out as a table so a change to `MATRIX` has to be deliberate
  here too; that the frontend mirror agrees; and **coverage**: the routers are
  read and any mutating route still reachable with a bare `Principal` fails.
- **Which stage the command centre nominates as next**
  (`test_overview_next_stage.py`) — a pure function over the stage list, so every
  combination that matters is stated rather than seeded. `None` may only mean
  every stage is finished.
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
  timeout and error mapping against a fake transport. The three Gemini
  adapters are each driven through a fake SDK client
  (`tests/test_llm_providers.py`, `tests/test_embedding_providers.py`,
  `tests/test_image_providers.py`), so every branch of the
  outcome-to-typed-error mapping is verified without a credit being spent —
  which is the point of the abstraction being a Protocol rather than a base
  class. Three things are asserted there that nothing else can assert:
  `structured()` returns a *validated Pydantic instance*, never a `dict` and
  never a raw SDK object; a reply that will not validate gets exactly one
  schema-constrained repair pass and then becomes a typed
  `ProviderInvalidResponse`, with nothing coerced or defaulted in between;
  and an embedding of the wrong width is **reported, never truncated**.
- **Image provider hardening** — returned format is *sniffed from the bytes*
  and PNG, JPEG and WebP are all recognised, so a row never claims a type the
  payload contradicts; provenance (provider, model, request id, latency,
  requested frame, returned MIME) is asserted; reference images become content
  blocks, a reference with no bytes is skipped rather than fatal, and more
  than the model accepts are trimmed. **Retry behaviour is tested as a
  spending control**: a retryable failure is repeated once by default, the
  limit is honoured and capped, a recovered retry returns the image, and a
  refusal, a bad request or a rejected credential is *never* repeated.
- **Credentials** — `TestSecretsNeverReachTheLogs` in the LLM and image suites:
  the key never reaches a user-facing message, a key-shaped string in a vendor
  error is redacted out of `detail` (by shape, in `ProviderError.__init__`),
  and nothing key-shaped appears in the request body the adapter builds.
- **Evaluator / Guardian** — scoring maths, ranking order, tie-breaks, and that a
  prohibited-claim violation always yields `NEEDS_REVISION`.
- **Revision delta** — KEEP fields are provably unchanged after applying a delta.
- **Per-channel copy** — a specification with no overrides resolves to its
  defaults and renders to **byte-identical PNG output**, asserted on the pixels
  rather than on the layout object: the resolver sits upstream of wrapping and
  the shrink loop, so only the bytes cover all of it. A payload with the
  `channel_copy` key *deleted* still validates, which is the
  backward-compatibility promise that made the migration unnecessary. An
  override changes only its own channel; a partial override inherits the rest;
  a per-channel call to action is locked exactly as the default one is
  (`locked_leaf` matches the last path segment, so
  `channel_copy.linkedin.cta` cannot walk past a lock that `cta` would hit).
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
- per-channel copy across the seams a pure function cannot reach: an unapproved
  draft override never renders (composition refuses while the latest version is
  unapproved) and an approved one does; an override may only name a channel the
  **Campaign Specification** declares, and the refusal names the ones that are
  allowed; the composition editor checks a call to action against that
  channel's *own* approved words, so the channel's CTA is accepted and the
  campaign default is refused on that same channel; three channels render three
  different headlines into three distinct files
- provider failure injection: an image provider that always fails must produce
  `FAILED` jobs, a surviving run, and a visible reason
- **role enforcement over HTTP** (`test_role_enforcement.py`): one user with one
  membership per role, every capability's representative route, asserted both
  ways. The permitted case asserts "not 403" because the guard is a dependency
  and runs before any row is looked up — so a permitted caller on an absent
  campaign is a `404`, which proves the guard let them past without seeding a
  whole campaign per row of the table. One route is run to completion so the
  guard is shown to let real work through, and a role is asserted not to cross
  organizations
- **a creative stage that exists in rows but not in a checkpoint**
  (`test_creative_row_backed.py`): the shape `seed_benchmark.py` produces. The
  seeded directions and plan are read back, no gate is invented, starting the
  stage changes nothing, and the repository refuses to replace an approved
  payload — while a campaign *with* a checkpoint still parks on Gate 1, which is
  the boundary between the two paths
- **keyset pagination** (`test_pagination.py`): walking the pages yields every
  row exactly once, each list keeps the order its screen already had, a row
  inserted mid-walk cannot hide another (the failure offset pagination has), and
  a cursor from another list is refused rather than becoming a 500

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
