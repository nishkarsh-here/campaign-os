# FINAL_RELEASE_AUDIT.md

Read-only release audit of `campaign-os` at **M11**. Nothing was implemented,
refactored or fixed. The only writes were the demo seed's own `--reset` (run to
verify Audit 6, scoped to the demo brand) and this file.

**Audited:** 2026-09-14 · `/Users/nishkarsh/Projects/campaign-os` · branch `main`

---

## 1. RELEASE STATUS

# READY FOR PRESENTATION

All seven quality gates pass, all ten M11 acceptance properties verify, the
architecture freeze held, every security boundary holds, and the complete demo
path is reproducible offline.

**Two things must happen before submission. Neither is a code defect.**

1. **M11 is uncommitted** — 20 modified files and 2 new test files are sitting
   in the working tree. The repository currently contains M0–M10 only.
2. **`docs/DEMO_SCRIPT.md` has drifted from the seeded demo.** A presenter
   following it would point at the screen and say "Brand check: **PASS**" while
   it reads "**Needs you**", and say "Creative Specification v2" where it is now
   v3. The software is right; the script is stale.

Both are reported below and deliberately not fixed.

---

## 2. Repository state

```
branch         main  (tracking origin/main, in sync)
HEAD           c20bb82  campaign-os: AI marketing orchestration platform, Milestones 0-10
working tree   20 modified, 2 untracked — all M11
```

Every changed file belongs to M11 and is accounted for:

| Area | Files |
|---|---|
| Domain | `creative.py` (`ChannelCopy`, `ResolvedCopy`, `copy_for`, `channel_copy`), `revision.py` (`locked_leaf`) |
| Services | `layout_builder`, `composition_stage`, `creative_stage`, `revision_application`, `revision_planner`, `revision_stage`, `brand_guardian` |
| API | `schemas.py`, `routers/campaigns.py` |
| Frontend | `lib/api.ts`, `components/creative-director.tsx`, `creative/page.tsx` |
| Seed + docs | `seed_demo.py`, `CLAUDE.md`, `API_SPEC`, `UI_SPEC`, `DEMO_SCRIPT`, `ROADMAP` |
| New tests | `tests/test_channel_copy.py`, `tests/integration/test_channel_copy_flow.py` |

731 insertions, 61 deletions across 20 files.

**Nothing unsafe would be committed.** No `.env`, `.venv`, `node_modules`,
`.next`, storage directory, `__pycache__`, `.pyc`, log or temp file appears in
the change set. No secret-shaped string appears in any M11 file. Three
`.DS_Store` files exist on disk and are correctly ignored (`git check-ignore`
confirms) — untracked and unstageable.

**Verdict: understandable and safe to commit.**

---

## 3. Test results

```
pytest        1103 passed, 0 failed  (98.7s)
ruff check    All checks passed!
ruff format   166 files already formatted
mypy app      Success: no issues found in 109 source files   (--strict)
tsc --noEmit  exit 0
next build    Compiled successfully · Generating static pages (7/7)
alembic check No new upgrade operations detected             (head 0009, 9 migrations)
```

### Per-stage regression (Audit 2)

Every milestone's own suite, run individually:

| Stage | Result |
|---|---|
| Domain schemas | 32 passed |
| Brand Brain | 19 passed |
| Campaign Discovery | 7 passed |
| Reference Intelligence | 25 passed |
| Creative Director | 6 passed |
| Prompt compilation | 29 passed |
| Generation | 36 passed |
| Evaluation | 36 passed |
| Brand Guardian | 19 passed |
| Revision | 31 passed |
| Composition | 30 passed |
| Export / composition API | 15 passed |
| Node contracts | 46 passed |
| Organization isolation | 33 passed |

**M11 broke nothing.** All 1,067 pre-M11 tests pass unchanged; M11 added 36.

---

## 4. Security status

Targeted read-only review. No new findings; the three fixed in the M10 audit
remain fixed.

| Area | Status |
|---|---|
| Authentication | ✅ `DevStubAuthProvider` raises at construction under `APP_ENV=production`; identity binds on the IdP subject, not the email |
| Organization isolation | ✅ 26 scoped repositories registered and parametrized in the cross-tenant probe; a guard test fails if a new one is unregistered |
| Campaign isolation | ✅ 34 tenancy assertions in the campaign API suite |
| Brand isolation | ✅ 8 assertions |
| Reference isolation | ✅ covered by the campaign API suite |
| Generated asset isolation | ✅ 4 assertions |
| Final asset isolation | ✅ 5 assertions, including an asset id read through another campaign's URL |
| **Channel-copy tenancy** | ✅ **by construction** — see below |
| Storage addressing | ✅ **0 of 62 routes** take a storage key from the request; every byte route resolves a scope-checked row first |
| Path traversal | ✅ key pattern validation, `..` rejection, and a resolved-path containment check before any filesystem access |
| Unsafe filenames | ✅ every storage key is generated with an org/campaign prefix and a UUID |
| Secrets | ✅ none in the repository; `backend/.env` present and ignored |
| Provider error redaction | ✅ `redact_secrets` in `ProviderError.__init__`; 6 tests pass |
| Browser/server boundary | ✅ no `NEXT_PUBLIC_*` anywhere, no credential name in the frontend |

**Channel-copy tenancy.** `channel_copy` has **no data path of its own** — it
lives inside the `CreativeSpecification` JSONB payload. Every path that reads or
writes it goes through an already-scoped repository:

- `edit_specification` → `CampaignRepository(session, organization_id)` resolves
  the campaign first, then `CreativeSpecificationRepository(session, organization_id)`
- `_declared_channels` → `CampaignSpecificationRepository(session, organization_id)`
- composition → its own `CreativeSpecificationRepository(session, organization_id)`
- `copy_for` → a pure function, no I/O

So tenancy is **inherited**, and covered by the 26-repository probe. See
observation O-1: it is not *separately* asserted.

---

## 5. Architecture-freeze status

**The freeze held.** M11 added one optional field to an existing model.

| Frozen rule | Still true |
|---|---|
| Campaign Specification = source of truth | ✅ and it is now what constrains *which channels* may carry copy |
| Creative Specification = execution source | ✅ `channel_copy` lives on it; the prompt compiler is untouched |
| `LayoutSpec` = composition source | ✅ 9 references in the renderer; composition still reads the layout |
| LangGraph = orchestration | ✅ no node, contract, state field or thread changed; 46 contract tests pass |
| Provider Protocols | ✅ 6 protocols in `providers/base.py`, unchanged |
| Organization-scoped repositories | ✅ 41 usages, 26 probed |
| Versioned artifacts | ✅ `apply_revision` still pure; v1 asserted byte-identical after a channel revision |
| Human approvals | ✅ overrides pass through Gate 2 like every other field |

**Confirmed absent:**

- **No duplicate state model** — one `CampaignState`, in `app/graph/state.py`
- **No duplicate provider abstraction** — protocols only in `providers/base.py`
- **No hidden graph state** — no graph file changed
- **No second source of truth** — `channel_copy` is a field on the existing
  artifact, not a new one; `db/models.py` is unchanged, no migration, still 9
- **No direct provider call in business logic** — no SDK import outside
  `app/providers/`

---

## 6. M11 regression status

All ten properties verified directly, not inferred.

| # | Property | Result |
|---|---|---|
| 1 | `channel_copy` is optional | ✅ `{}` by default; a payload with the key **deleted** still validates |
| 2 | Absent overrides → byte-identical | ✅ **rendered PNG bytes compared**, not layout objects — the resolver sits upstream of wrapping and the shrink loop |
| 3 | Only declared channels | ✅ an undeclared channel is a `400` naming the allowed ones |
| 4 | Partial overrides inherit | ✅ an override sets `headline`; `cta` and `subhead` fall back |
| 5 | Per-channel CTA protected | ✅ `locked_leaf("channel_copy.linkedin.cta")` is true; needs an explicit unlock |
| 6 | Gate 2 controls overrides | ✅ composition **refuses** while a draft is unapproved; renders once approved |
| 7 | Single-channel revision | ✅ one headline moves; the other override and the default are untouched |
| 8 | Historical versions intact | ✅ v1's `channel_copy` unchanged, v2 has a new id and version |
| 9 | Guardian checks overrides | ✅ override text reaches `_specification_text`; a prohibited claim in an override is scanned |
| 10 | Composition resolves correctly | ✅ three channels render three different headlines, live |

36 M11 tests pass (25 unit, 11 integration).

---

## 7. Demo status

| Requirement | Result |
|---|---|
| Resettable | ✅ `--reset` removed exactly 1 demo brand; the 3 other developer brands were untouched |
| Idempotent | ✅ two plain runs both no-op identically |
| **Deterministic** | ✅ **two `--reset` runs produced identical output** — same verdict, same top score (80.3), same counts |
| Offline | ✅ `_require_mocks` refuses a live provider; `DEMO_MODE=true` refuses to start against one |
| No Gemini required | ✅ `llm=mock image=mock embedding=mock storage=local` |
| All workflow stages | ✅ discovery → human edits → both gates → generation → evaluation → Guardian → revision → regeneration → re-evaluation → re-check → composition |
| At least one revision | ✅ 1 revision round, Creative Specification v3 |
| Per-channel copy | ✅ 2 of 3 channels overridden |
| Multi-channel final assets | ✅ 3 assets, all servable |

Rendered output from the live seeded campaign:

| Channel | Headline | CTA |
|---|---|---|
| Instagram post | Built to outlast the building it clads | Request the specification pack |
| Instagram story | **Outlasts the building** | Request the specification pack |
| LinkedIn | **Specified for a 40-year facade life** | **Request the FS-9 specification pack** |

The post deliberately has no override, so the demo shows both halves of the
feature: a channel that differs and a channel that inherits.

**One change since M10, and the demo script has not caught up.** The seed now
writes per-channel copy as a human edit before Gate 2. That changes the
specification, which changes the compiled prompt, which changes the mock
plates — and the mock Guardian is deterministic *from the plate's pixels*. The
seeded demo now ends with the **selected creative rejected** (5 PASS, 1 REJECT
across 6 checks), so the command centre shows `ATTENTION · Brand check`, not
six green stages.

This is correct behaviour on the plates it was given, and it is stable across
runs. It is a **documentation** problem, reported under §8 and O-2.

---

## 8. Documentation status

All 13 documents present. Stale statements only — nothing was modified.

| Document | Finding |
|---|---|
| `README.md` | ⚠️ **"Milestones 0–10 complete"** and **"1,067 passing"**. No mention of per-channel copy in the feature walkthrough. |
| `CLAUDE.md` | ✅ current — M11 section, rules, and the freeze statement |
| `docs/API_SPEC.md` | ✅ current — the per-channel copy section is accurate |
| `docs/UI_SPEC.md` | ✅ current |
| `docs/ROADMAP.md` | ✅ current — M11 row present and marked ✅ |
| `docs/DEMO_SCRIPT.md` | ⚠️ **three stale claims** — "six stages all green" (line 32), "**Brand check: PASS**" (line 60), "Creative Specification **v2**" (lines 60, 196 — now v3). It *does* cover per-channel copy correctly. |
| `docs/DATABASE_SCHEMA.md` | ⚠️ the `creative_specifications` section does not mention that its payload now carries `channel_copy`. No migration was needed, so nothing is wrong — just undocumented. |
| `docs/PRODUCT_SPEC.md` | ⚠️ §11 Channel variants still says *"Strategy and brand elements are preserved; only the `LayoutSpec` geometry changes."* After M11 the **copy may change too**. |
| `docs/ARCHITECTURE.md` | ⚠️ 14 ADRs, none for M11. Defensible — M11 made no architectural decision — but the freeze statement does not acknowledge that M11 landed under it. |
| `docs/TESTING.md` | ⚠️ does not list the M11 test layer |
| `docs/GRAPH_SPEC.md` | ✅ current — M11 touched no graph node |
| `docs/DEPLOYMENT.md` | ✅ current — no new setting, service or migration |
| `M10_FINAL_REPORT.md` | ✅ accurate **as a record of M10**; its "1,067 passing" is correct for the milestone it reports |

---

## 9. Known limitations

Verified as still accurate. None prevents presentation or submission.

1. **Live Gemini generation is unverified.** One controlled smoke test was run
   in M10; the provider rejected the credential
   (*"The image service rejected this workspace's credentials"*). The request
   was built and sent, so the failure is at the credential, not in the adapter —
   which is covered by unit tests driving a fake SDK client. Mock mode is the
   guaranteed path, by design.
2. **Mock providers are deterministic fixtures, not models.** They produce
   coherent, reproducible output and exercise every code path, but the plates
   are generated shapes and the scores are derived from pixels. The demo shows
   the *workflow* faithfully; it does not show model quality.
3. **Background work runs in the API process** (ADR-012) and does not survive a
   restart. Startup reconciliation turns an abandoned job into a visible,
   retryable failure rather than a permanent spinner; across multiple instances
   that reconciliation is a grace-window heuristic rather than a guarantee.
4. **Dev authentication is not a security model.** `AUTH_PROVIDER=dev_stub`
   authenticates every caller as the same user and refuses to construct under
   `APP_ENV=production`. Supabase Auth is wired behind the seam but not enabled.
5. **Typography falls back** to Pillow's bundled face unless the brand uploaded
   one. No typeface is identified, downloaded or substituted by name.
6. **Print is refused, not supported.** No CMYK, bleed, crop marks or PDF; the
   API refuses a print channel with a reason.
7. **No frontend automated test harness.** `package.json` has no `test` script
   and no Jest/Vitest/Playwright/Cypress/Testing Library dependency. The UI is
   covered by TypeScript, the production build, API contract tests, and manual
   browser walkthroughs — not by automated component or end-to-end tests.
8. **Local storage does not work behind more than one instance.**
9. **No rate limiting.** Spend is bounded by batch size and timeouts, not by
   request volume.
10. **Jobs have no progress detail** — `PENDING`, `RUNNING`, or terminal.
11. **Switching embedding provider invalidates stored vectors.**
12. **`/v1/docs` is served in every environment.**

### New in M11

13. **A channel override is all-or-nothing per leaf.** There is no way to say
    "this channel has *no* subhead" — a blank inherits. The layout drops a
    subhead where the frame has no room, which is a geometry decision, so this
    has not been needed. Recorded because the asymmetry is real.
14. **A variant never invents an element.** If the source layout dropped the
    subhead, an override carrying one cannot bring it back. Asserted by a test.
15. **`channel_copy` is sent whole, not patched per channel.** A partial patch
    of a nested map is ambiguous about deletion. Fine at this size; it would
    not scale to dozens of channels.

---

## 10. Release blockers

**None.**

No defect found in this audit prevents presentation or submission. The two
outstanding items in §1 are a commit and a documentation edit.

---

## 11. Non-blocking observations

### O-1 · Channel-copy tenancy is inherited, not separately asserted — ROADMAP

`channel_copy` has no data path of its own, and every path that touches it is
already scoped (§4). But `test_channel_copy_flow.py` contains no cross-tenant
assertion of its own — it relies on the 26-repository probe. That is
structurally sound and worth one explicit test, for the same reason every other
resource has one.

### O-2 · The demo script promises a PASS the seed no longer produces — **fix before presenting**

`docs/DEMO_SCRIPT.md` tells a presenter to point at "**Brand check: PASS**" and
"six stages all green". The seeded demo now shows `ATTENTION · Brand check`
because the selected creative was rejected (see §7). The behaviour is correct
and deterministic; the script is stale.

Either outcome makes a good demo — a rejection arguably shows the Guardian
doing its job — but the script must match what is on screen. This is the
highest-priority item in this report and it is a documentation edit.

### O-3 · README and `PRODUCT_SPEC` §11 predate M11 — ROADMAP

The README still reads "Milestones 0–10" with "1,067 passing", and
`PRODUCT_SPEC` §11 still says only geometry changes between channels. Both were
true before M11 and are now understatements of what the product does.

### O-4 · `DATABASE_SCHEMA` does not mention `channel_copy` — ROADMAP

No migration was needed because the field lives in an existing JSONB payload,
which is exactly why it is easy to forget to document. Worth a line in the
`creative_specifications` section.

### O-5 · No frontend test harness — ROADMAP

Listed as limitation 7. Named here too because it is the largest single gap in
the project's otherwise strong automated coverage, and it is a deliberate scope
choice rather than an oversight.

### O-6 · Fake API keys in a test file — not a finding

`backend/tests/test_image_providers.py` contains `AIzaSyD1234567890abcdefgh` and
similar. They are the fixtures for the secret-redaction test — the strings being
asserted as redacted. Flagged so a future secret scan is not mistaken for a leak.

---

## 12. Exact commands and results

```
$ git branch --show-current
main
$ git log -1 --format="%h %s"
c20bb82 campaign-os: AI marketing orchestration platform, Milestones 0-10
$ git status -sb | head -1
## main...origin/main
$ git status --short | wc -l
22          # 20 modified + 2 untracked, all M11
$ git diff --stat | tail -1
20 files changed, 731 insertions(+), 61 deletions(-)
$ git check-ignore -v .DS_Store frontend/.DS_Store backend/.DS_Store
(all three ignored, none tracked)

--- Audit 10: quality gate ---
$ uv run pytest -q
1103 passed, 5 warnings in 99.97s
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
166 files already formatted
$ uv run mypy app
Success: no issues found in 109 source files
$ uv run alembic check
No new upgrade operations detected.
$ uv run alembic heads
0009_final_composition (head)          # 9 migrations, unchanged by M11
$ npx tsc --noEmit
exit 0
$ npx next build
✓ Compiled successfully · ✓ Generating static pages (7/7)

--- Audit 2: per-stage ---
domain schemas 32 · Brand Brain 19 · Discovery 7 · References 25
Creative Director 6 · Prompt compilation 29 · Generation 36 · Evaluation 36
Brand Guardian 19 · Revision 31 · Composition 30 · Export/API 15
node contracts 46 · org isolation 33

--- Audit 3: M11 properties (live) ---
1 optional:              True
1 pre-M11 payload ok:    True
2 other channel clean:   True
4 partial inherits:      True
5 per-channel CTA lock:  True | default: True | headline not locked: True
7 one channel only:      True
8 v1 intact:             True | v2 is v2 | new id: True
9 Guardian sees it:      True
$ uv run pytest tests/test_channel_copy.py tests/integration/test_channel_copy_flow.py -q
36 passed

--- Audit 4: freeze ---
class CampaignState:        app/graph/state.py           (one)
Protocols:                  app/providers/base.py         (6)
provider SDK outside providers/:  none
db/models.py changed:       no
migrations:                 9 (unchanged)
channel_copy column:        none (lives in the existing JSONB payload)

--- Audit 5: security ---
routes taking a storage key from the request: none (of 62)
scoped repositories probed:  26
redaction tests:             6 passed
NEXT_PUBLIC_* in frontend:   none

--- Audit 6: demo ---
$ uv run python scripts/seed_demo.py            # twice
demo data already present (brand a5c0345f-…). Use --reset to rebuild.   (both runs)
$ uv run python scripts/seed_demo.py --reset    # twice
run 1: guardian=REJECT  top_score=80.3  revisions=1  assets=3
run 2: guardian=REJECT  top_score=80.3  revisions=1  assets=3      # deterministic
brands before / after reset: Fenesta Systems 1, Northline Facades 1,
                             Northline M4 1, Northline Materials 1   (unchanged)
DEMO_MODE + gemini image:  REFUSED
DEMO_MODE + gemini llm:    REFUSED
DEMO_MODE + all mock:      ACCEPTED
/v1/health: llm=mock image=mock embedding=mock storage=local demo_mode=True

--- Audit 8: routes ---
campaign overview 200 · discovery 200 · references 200 · creative 200
generation 200 · evaluation 200 · refine 200 · composition 200
brands 200 · campaigns 200 · workspace 200
final assets: linkedin 200 image/png 30,758B · story 200 52,136B
              post 200 40,514B · ?download=true 200
brand brain: 1 document, 1 asset, 10 accepted facts,
             3 colours, 3 prohibited claims, 1 product
```

---

## 13. Recommended next action

**Commit M11, then reconcile the demo script.** In that order.

```bash
cd /Users/nishkarsh/Projects/campaign-os && git add . && git commit -m "M11: per-channel creative copy"
```

`.gitignore` was verified against the exact change set — no secret, venv,
`node_modules`, `.next`, storage directory or bytecode is included.

```bash
git push
```

**Then, before presenting**, resolve O-2 — the one item that would make a
presenter say something false on stage. Two honest options:

- **Update the script** to match what the seed produces: the Guardian rejects
  the selected creative, and the campaign shows `ATTENTION · Brand check`. This
  is arguably the better demo — it shows the Guardian catching something rather
  than rubber-stamping — and it needs no code change.
- **Or adjust the seed** so the selected creative is one that passed, and keep
  the current script. That is a seed change, not a product change.

Optional, in priority order: O-3 (README milestone range, test count, and a
line about per-channel copy), O-4 (`channel_copy` in `DATABASE_SCHEMA`), O-1
(one explicit channel-copy tenancy test), O-5 (a frontend test harness — a
milestone in its own right).

## FINAL RECOMMENDATION

# READY FOR PRESENTATION

after committing M11 and reconciling `docs/DEMO_SCRIPT.md` with the seeded
demo's Brand-check outcome. No code change is required.
