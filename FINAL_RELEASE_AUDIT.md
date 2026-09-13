# FINAL_RELEASE_AUDIT.md

Read-only release audit of `campaign-os` at M10. Nothing was implemented,
refactored or fixed. The only writes were to the demo database (the seed's own
`--reset`, run to verify check 13) and this file.

**Audited:** 2026-09-13 · repository `/Users/nishkarsh/Projects/campaign-os`

---

## RELEASE STATUS: **BLOCKED**

One blocker, and it is not in the code.

> **The repository has no commits.** `git log` reports *"your current branch
> 'main' does not have any commits yet"* and `git ls-files` returns 0. Every one
> of the 224 files that make up this project is untracked.

Everything else passes. All twelve mechanical gates are green, the demo path
works end to end, and the documentation is accurate. The product is
presentation-ready; the *repository* is not yet a repository.

This is a one-command fix and it is deliberately left to you.

---

## Verified checks

| # | Check | Result |
|---|---|---|
| 1 | Git working tree and repository state | ❌ **BLOCKER** — 0 commits, 224 untracked files. `.gitignore` itself is correct. |
| 2 | No accidental secrets or credentials committed | ✅ Nothing is committed at all; and of the 224 files that *would* be, none is a secret or artefact. |
| 3 | `.env.example` matches `Settings` | ✅ Asserted both ways by a test. |
| 4 | README setup instructions match the project | ✅ Every command and claimed number verified. |
| 5 | `DEMO_SCRIPT.md` matches the current UI and seed | ✅ Every claim checked against a fresh seed. |
| 6 | `DEPLOYMENT.md` matches the actual setup | ✅ Seven concrete claims spot-checked. |
| 7 | Migrations complete, `alembic check` clean | ✅ 9 migrations, head `0009_final_composition`, no drift. |
| 8 | Test suite passes | ✅ **1,067 passed**, 0 failed. |
| 9 | Ruff passes | ✅ check + format, 164 files. |
| 10 | mypy `--strict` passes | ✅ 109 source files. |
| 11 | TypeScript passes | ✅ `tsc --noEmit` exit 0. |
| 12 | Next production build passes | ✅ compiled, 15 routes, 7 static pages. |
| 13 | Demo seed resettable and idempotent | ✅ Plain run is a no-op twice; `--reset` removed exactly 1 demo brand and rebuilt 3 final assets. |
| 14 | Demo mode cannot invoke live providers | ✅ Enforced at startup; three provider combinations refused. |
| 15 | Main demo routes exist | ✅ All 13 app routes present and returning 200. |
| 16 | No stale "future feature" wording on implemented screens | ✅ No user-visible matches in `src/`, none in the docs about implemented features. |
| 17 | No broken internal links in documentation | ⚠️ 18/18 relative links resolve; **one intra-page anchor is wrong** (non-blocking, below). |
| 18 | No obviously unfinished UI sections | ✅ No TODO/FIXME/placeholder/lorem in `src/`; overview renders complete. |
| 19 | Known limitations honestly documented | ✅ 10 numbered limitations in the report, plus §9 of the deployment guide. |
| 20 | Gemini live limitation clearly documented | ✅ In README, M10 report §10, and the demo script's "what not to promise". |
| 21 | Architecture-freeze rules present | ✅ In `M10_FINAL_REPORT.md` §"Architecture freeze" and `CLAUDE.md`. |
| 22 | No Milestone 11 work started | ✅ Zero references anywhere; ROADMAP ends at 10 ✅; `CLAUDE.md` says "Next: nothing." |

---

## Blockers

### B-1 · The repository has no commits

```
$ git log --oneline -5
fatal: your current branch 'main' does not have any commits yet

$ git ls-files | wc -l
0

$ git status --short
?? .env.example
?? .gitignore
?? ARCHITECTURE_REVIEW.md
?? CLAUDE.md
?? M10_FINAL_REPORT.md
?? M1_SECURITY_AUDIT.md
?? README.md
?? backend/
?? docs/
?? frontend/
```

**Why it blocks.** A submission is a repository. Without a commit there is no
history, no hand-over artefact, nothing to clone, and no protection against an
accidental deletion of the working tree. Ten milestones of work currently exist
only as files on one disk.

**Why it is low-risk to fix.** `.gitignore` is already correct and was verified
against the exact file set git would stage:

```
$ git add -An --dry-run . | wc -l
224

$ grep -E "\.env$|\.venv/|node_modules/|\.next/|/storage/|__pycache__" <staged list>
(no matches)
```

No secret, virtualenv, `node_modules`, `.next`, local storage directory or
bytecode file would be included. `backend/.env` exists on disk and is correctly
ignored (`git check-ignore` confirms, via `.gitignore:2`).

**Not fixed, per the audit's instructions.** See *Recommended next action*.

---

## Non-blocking observations

### O-1 · One documentation anchor does not resolve — ROADMAP

`docs/DEPLOYMENT.md:6` links to `#what-this-deployment-cannot-do`; the heading
is `## 9. What this deployment cannot do`, whose GitHub slug is
`#9-what-this-deployment-cannot-do`. The same link **from README is correct** —
only the deployment guide's own intra-page link is missing the `9-`. Cosmetic;
the section is two screens below the link.

### O-2 · The development database holds 14 non-demo campaigns — ROADMAP

The campaigns list shows 15 campaigns: the seeded one plus 14 left over from
earlier milestone walkthroughs (`Fenesta Systems` ×11, `Northline Materials`
×2, `Northline M4` ×1). This is **database state, not a code defect** —
`--reset` is correctly scoped to the demo brand and removed exactly 1 brand,
leaving a developer's own work alone, which is the right behaviour.

`docs/DEMO_SCRIPT.md` already documents the remedy (seed into a fresh
`campaign_os_demo` database for a pristine screen) and the seed prints the
campaign URL, so the walkthrough never depends on picking a row out of the list.
Worth doing before a presentation; not a release blocker.

### O-3 · "13 routes" in the README is a defensible count, not an exact one — ROADMAP

The Next build reports 15 route entries. The README's 13 counts the application
routes, excluding `/` (the marketing landing) and `/_not-found`. Accurate but
mildly ambiguous.

### O-4 · Fake API keys appear in a test file — not a finding

`backend/tests/test_image_providers.py` contains `AIzaSyD1234567890abcdefgh`
and similar. These are the **fixtures for the secret-redaction test** — they are
the strings being asserted as redacted. Obviously synthetic, and removing them
would remove the test. Flagged here only so a future secret scan is not
mistaken for a real leak.

---

## Exact commands and results

```
$ git rev-parse --show-toplevel
/Users/nishkarsh/Projects/campaign-os
$ git branch --show-current
main
$ git log --oneline -5
fatal: your current branch 'main' does not have any commits yet
$ git ls-files | wc -l
0
$ git add -An --dry-run . | wc -l
224
$ git check-ignore -v backend/.env
.gitignore:2:.env	backend/.env

$ cd backend && uv run pytest -q
1067 passed, 5 warnings in 97.63s

$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
164 files already formatted

$ uv run mypy app
Success: no issues found in 109 source files

$ uv run alembic check
No new upgrade operations detected.
$ uv run alembic heads
0009_final_composition (head)
$ ls migrations/versions/*.py | wc -l
9

$ cd ../frontend && npx tsc --noEmit
exit=0
$ npx next build
✓ Compiled successfully in 936ms
✓ Generating static pages (7/7)
15 route entries

$ uv run pytest tests/test_config.py -k Example
2 passed          # .env.example <-> Settings, both directions

$ curl -s localhost:8000/v1/openapi.json | jq '.paths | length'
62

$ uv run python scripts/seed_demo.py          # run 1
demo data already present (brand ee617ead-…). Use --reset to rebuild.
$ uv run python scripts/seed_demo.py          # run 2 — identical
demo data already present (brand ee617ead-…). Use --reset to rebuild.
$ uv run python scripts/seed_demo.py --reset
removed 1 demo brand(s) and everything under them
…
done.  campaign 8faecf83-…  final assets 3

# Demo-mode provider guard (Settings constructed directly)
REFUSED   DEMO_MODE=true + IMAGE_PROVIDER=gemini
REFUSED   DEMO_MODE=true + LLM_PROVIDER=gemini
REFUSED   DEMO_MODE=true + EMBEDDING_PROVIDER=gemini
ACCEPTED  DEMO_MODE=true + all mock

$ curl -s localhost:8000/v1/health
demo_mode = True | providers: llm=mock image=mock embedding=mock
                               storage=local search=none auth=dev_stub

# Freshly seeded campaign, read through the overview endpoint
stages all DONE:        True (DONE DONE DONE DONE DONE DONE)
Creative Specification: v2
Brand check:            PASS
revision rounds:        1
channels:               3  (instagram_post, instagram_story, linkedin)
final assets:           3
ranked assets:          6

# Every demo route
/app/campaigns/{id}/overview     200
/app/campaigns/{id}             308  (trailing-slash redirect)
/app/campaigns/{id}/inspiration  200
/app/campaigns/{id}/creative     200
/app/campaigns/{id}/generate     200
/app/campaigns/{id}/evaluate     200
/app/campaigns/{id}/refine       200
/app/campaigns/{id}/compose      200
/app/brands                      200
/app/campaigns                   200

# Documentation
18/18 relative links resolve
1 intra-page anchor does not (O-1)
14 ADRs in ARCHITECTURE.md — README claims 14
0 references to Milestone 11 anywhere
```

---

## Current test count

**1,067** tests, all passing.

```
1067 tests collected
1067 passed, 0 failed, 5 warnings in 97.63s
```

Split by marker: 564 unit (`-m unit`), the remainder integration against a real
PostgreSQL with mock providers. No test reaches an external service —
`APP_ENV=test` refuses a non-mock provider at startup.

---

## Current build status

| Gate | Command | Result |
|---|---|---|
| Tests | `uv run pytest` | ✅ 1,067 passed |
| Lint | `uv run ruff check .` | ✅ All checks passed |
| Format | `uv run ruff format --check .` | ✅ 164 files formatted |
| Types (py) | `uv run mypy app` | ✅ 109 files, no issues |
| Types (ts) | `npx tsc --noEmit` | ✅ exit 0 |
| Frontend | `npx next build` | ✅ compiled, 15 routes, 7 static |
| Migrations | `uv run alembic check` | ✅ no drift, head `0009` |

---

## Current known limitations

Reproduced from `M10_FINAL_REPORT.md` §9 and verified as still accurate. All are
documented in the README, the deployment guide and the demo script.

1. **Background work does not survive a restart.** In-process `asyncio` tasks
   (ADR-012). Startup reconciliation turns an abandoned job into a visible,
   retryable failure rather than a permanent spinner.
2. **That reconciliation is a heuristic across instances** — it only touches rows
   older than the generation timeout plus five minutes. Exact with one instance.
3. **Local storage does not work behind more than one instance.**
4. **No rate limiting.** Spend is bounded by batch size and timeouts, not by
   request volume.
5. **Typography falls back** to Pillow's bundled face when a brand has not
   uploaded one. No typeface is identified or substituted by name.
6. **Print is refused, not supported.** No CMYK, bleed, crop marks or PDF.
7. **Jobs have no progress detail** — `PENDING`, `RUNNING`, or terminal.
8. **Switching embedding provider invalidates stored vectors.**
9. **The dev auth stub is not a security model** (guarded against production).
10. **`/v1/docs` is served in every environment.**

**Gemini live status — unchanged and correctly documented.** One controlled
smoke test was run in M10; the provider rejected the credential. The adapter
built and sent the request, so the failure is at the credential, not in our
code. The adapter is covered by unit tests driving a fake SDK client. Mock mode
is the guaranteed demonstration path, by design.

---

## Recommended next action

**One command, then the audit is clean.**

```bash
cd /Users/nishkarsh/Projects/campaign-os
git add .
git commit -m "campaign-os: Milestones 0-10 complete"
```

`.gitignore` was verified against the exact staged set: no secret, venv,
`node_modules`, `.next`, storage directory or bytecode file is included.

Optionally, before presenting:

1. Fix the anchor in `docs/DEPLOYMENT.md:6` (`#9-what-this-deployment-cannot-do`).
2. Seed into a clean database so the campaigns list shows only the demo
   campaign — `createdb campaign_os_demo`, point `DATABASE_URL` at it, migrate,
   then `uv run python scripts/seed_demo.py --reset`.
3. Push to a remote, so the submission is a URL rather than a directory.

Neither optional item affects the product. **Re-run this audit after the commit
and the status becomes READY.**
