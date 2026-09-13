# M1_SECURITY_AUDIT.md

Targeted security and correctness audit of the completed Milestone 1
implementation. Conducted 2026-09-12, before any Milestone 2 work.

Method: direct inspection of the current code, migrations, live database schema
and tests, plus executed probes. Findings marked **verified** were reproduced by
running code, not inferred from reading it. No multi-agent review was used.

---

## 1. Scope

Audited, as requested:

| # | Area | Files inspected |
|---|---|---|
| 1 | Organization / tenancy isolation | `repositories/base.py`, `projects.py`, `organizations.py`, `api/routers/*` |
| 2 | Authentication boundary | `auth/base.py`, `auth/dev_stub.py`, `auth/registry.py`, `api/deps.py` |
| 3 | Authorization | `domain/common.py` (Role), `memberships` model, `api/deps.py` |
| 4 | Repository scoping | every `ScopedRepository` subclass; SELECT / UPDATE / DELETE / pagination / by-id |
| 5 | API authorization and input validation | all 9 M1 endpoints, `api/errors.py`, `api/middleware.py`, `api/schemas.py` |
| 6 | Storage access | `providers/local/storage.py` and its (absent) API boundary |
| 7 | LangGraph checkpoint persistence | `graph/serde.py`, `tests/integration/r2_resume_runner.py` |
| 8 | Database integrity | `migrations/versions/0001_foundation.py`, `db/models.py`, live schema |
| 9 | Secrets / configuration | `config.py`, `.env.example`, `next.config.mjs`, `frontend/src` |

Out of scope by instruction, and not touched: production authentication, RBAC,
and every Milestone 2+ feature.

---

## 2. Findings

Two real defects, both fixed. Five observations recorded without code change.

| ID | Finding | Severity | Status |
|---|---|---|---|
| **A-1** | Identity resolution fell back to email, enabling account takeover under any real IdP | **Critical** | **Fixed** |
| **A-2** | Checkpoint deserialization allowlist was silently allow-everything | **High** | **Fixed** |
| A-3 | `/v1/health` discloses provider configuration to unauthenticated callers | Low | Accepted, documented |
| A-4 | `memberships` has no standalone index on `user_id` | Informational | Accepted |
| A-5 | `thread_id = campaign_id` — M4 must verify org ownership before resuming | Informational | Recorded for M4 |
| A-6 | `ExecutionError.detail` is checkpointed; adapters must not put credentials there | Informational | Recorded for M6 |
| A-7 | Storage has no organization scoping, and `/v1/files` is not implemented | Informational | Intentional |
| — | PATCH had no cross-tenant regression test (code was correct) | Coverage gap | Test added |

---

### A-1 — Identity resolution fell back to email · **Critical** · Fixed

**Why it is a defect.** `UserRepository.upsert_from_identity` resolved a caller
to a database row like this:

```python
existing = await self.by_subject(subject) or await self.by_email(email)
if existing is not None:
    if existing.auth_subject is None:
        existing.auth_subject = subject
    ...
    return existing
```

`get_current_user` calls this on **every authenticated request**
(`api/deps.py:57`), and `get_principal` then resolves memberships from the row
it returns. So the sequence for an attacker whose identity provider asserts a
victim's email address is:

1. `by_subject("idp|attacker")` → `None` — the attacker has never been seen.
2. `by_email("victim@corp.test")` → **the victim's row**.
3. `existing.auth_subject` is `"idp|victim"`, not `None`, so it is left alone —
   and the victim's row is returned anyway.
4. The attacker is now authenticated as the victim, in every organization the
   victim belongs to.

The second branch is a separate hole in the same function: any row with a null
`auth_subject` — seeded, invited, or imported — could be claimed outright by
whoever first presented that email.

Email is not proof of identity. An IdP asserting an unverified email, a
self-service signup, or a provider that lets a user set their own address all
break this. The docstring described the behaviour as a feature ("link an
existing email to a new identity provider"), so it was a deliberate design
choice that was wrong, not a typo.

**Exploitable today?** No. The dev stub asserts one fixed `(subject, email)`
pair, so only one identity exists. That is precisely why it mattered: this is
the seam production auth plugs into, and Milestone 1's stated goal was to keep
the architecture "compatible with real authentication later". The hole would
have shipped silently with the provider swap, with no code change to draw
attention to it.

**Evidence.** `app/repositories/organizations.py:101` (pre-fix), reached from
`app/api/deps.py:57`. Now reproduced as a failing-before/passing-after
regression test — `test_an_unknown_subject_with_a_taken_email_is_refused` and
`test_an_attacker_cannot_inherit_the_victims_memberships`.

---

### A-2 — Checkpoint allowlist was allow-everything · **High** · Fixed

**Why it is a defect.** `docs/R2_CHECKPOINT_SPIKE.md` states that a checkpoint
row "can only reconstruct types we have declared". It could not. `build_serde()`
was:

```python
JsonPlusSerializer().with_msgpack_allowlist(allowlisted_types())
```

`JsonPlusSerializer()` with no arguments defaults its allowlist to `True`
(allow everything) unless `LANGGRAPH_STRICT_MSGPACK` is set in `os.environ` at
import time. And `with_msgpack_allowlist()` **short-circuits on a permissive
base** — it returns the same object unchanged. All 63 declared types were
silently discarded.

The environment variable did not save it in the running application either:
`LANGGRAPH_STRICT_MSGPACK=true` lives in `backend/.env`, which pydantic-settings
reads into `Settings` — never into `os.environ`. The library's module-level
check never saw it. The R-2 test passed only because it sets the variable
explicitly in the subprocess environment.

Net effect: a documented security control was inert in exactly the process that
needed it, while both the document and the test suite reported it as active.
This is the failure mode `CLAUDE.md` rule 9 exists to prevent.

**Evidence — executed, not inferred:**

```
fresh serializer base allowlist : True
after with_msgpack_allowlist    : True
returned the SAME object?       : True

build_serde() (env var unset)   : allow-all? True
build_serde() (env var set)     : allow-all? False | entries: 63
```

**Impact.** Defence-in-depth, not a live breach: nothing untrusted writes to the
checkpoint tables today. But a permissive deserializer instantiates whatever
type a checkpoint row names, so anyone who could write to `checkpoints` could
choose what gets constructed during a resume.

---

### A-3 — `/v1/health` discloses provider configuration · Low · Accepted

`GET /v1/health` requires no authentication and returns the selected `llm`,
`image`, `embedding`, `storage`, `search` and `auth` providers. An unauthenticated
caller learns the technology stack.

Not fixed, deliberately. The most sensitive value cannot occur in production:
`DevStubAuthProvider.__init__` raises under `APP_ENV=production`, so
`"auth": "dev_stub"` is impossible there. The remainder is ordinary stack
disclosure, and dependency status is the normal purpose of a health endpoint.
Changing working code on a Low finding is outside this audit's remit.

**Recommendation for Milestone 10 (deployment):** keep `status` and `database`
public for the load balancer, and move the `providers` map behind
authentication or an internal-only route.

---

### A-4 — No standalone index on `memberships.user_id` · Informational

`organizations_for_user(user_id)` filters on `user_id` alone, but the only
composite index is `(organization_id, user_id)` — wrong leading column, so the
query sequentially scans `memberships`. It runs on every request that omits the
`X-Organization-Id` header.

Not a defect and not a security issue; at Milestone 1 row counts it is
unmeasurable. Recorded rather than fixed because the instruction forbids
speculative schema changes without a confirmed defect. Revisit if membership
counts grow.

---

### A-5 — `thread_id = campaign_id` · Informational · For Milestone 4

The checkpoint thread identifier is the campaign id, so threads are isolated by
construction: two campaigns cannot collide, and a UUID is not guessable in any
practical sense. No production code maps a request to a thread yet — the only
caller is the spike runner, which takes it as an argument.

**The rule Milestone 4 must follow:** resolve the campaign through the
organization-scoped repository *first*, and derive `thread_id` from the row that
comes back. Taking a campaign id from the request and passing it straight to the
checkpointer would resume another tenant's execution, bypassing every guard
audited here, because the checkpointer has no concept of an organization.

---

### A-6 — `ExecutionError.detail` is checkpointed · Informational · For Milestone 6

`ExecutionError.detail` is documented as "log-side detail" and is excluded from
API responses, but it is a field of `CampaignState` and is therefore persisted
into checkpoint rows. A provider adapter that stored a raw vendor error — some
of which embed the request URL, and therefore a key — would write a credential
into the database.

The constraint for adapter authors: `detail` carries a sanitised message, never
a raw exception string, response body, or URL.

---

### A-7 — Storage has no organization scoping · Informational · Intentional

`LocalStorageProvider` treats keys as opaque and has no concept of an
organization, and `/v1/files/{storage_key}` is specified in `API_SPEC.md` but
**not implemented in Milestone 1**. There is therefore no storage API boundary
to bypass today.

The rule for whichever milestone implements it: keys must be
organization-prefixed, and the endpoint must resolve the owning row through a
scoped repository before serving bytes. Validating the key is not sufficient —
a well-formed key belonging to another organization is still a leak.

---

## 3. Severity summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | A-1 |
| High | 1 | A-2 |
| Low | 1 | A-3 |
| Informational | 4 | A-4, A-5, A-6, A-7 |

---

## 4. Evidence — areas verified clean

These were inspected and found correct. Listed so the audit says what it
checked, not only what it found.

**Repository scoping.** `ScopedRepository.get()` and `count()` both route
through `_scope()`; `ProjectRepository._scope()` additionally excludes
soft-deleted rows, so a deleted project cannot reappear through a query that
forgot the filter. Both subclasses override `_scope` (asserted by
`test_org_isolation.py`). `add()` runs `_assert_owned()`, which raises
`PermissionError` on an attempt to write into another organization.

**IDOR across every project endpoint.** `GET`, `PATCH` and `DELETE` on
`/v1/projects/{id}` all resolve the row through the scoped repository before
touching it; a valid UUID from another organization yields `None` and a `404`.
Verified at both layers: repository (`test_org_isolation.py`) and HTTP
(`test_api_workspace.py`). A malformed UUID also returns `404`, not `400`, so
probing distinguishes nothing.

**404 rather than 403.** Cross-tenant access is indistinguishable from
non-existence, at the project routes and at organization resolution in
`get_principal`. Response bodies were checked to confirm the foreign resource's
name does not appear.

**Pagination.** The keyset cursor is user-supplied but applied *after*
`self.scoped()`, so a cursor forged from another organization cannot widen the
result set. A malformed cursor is a typed `400`, and the walk-every-page test
confirms no rows are skipped or repeated.

**Authentication boundary.** Identity resolution goes through the
`AuthProvider` Protocol; no business logic imports `DevStubAuthProvider`
(`auth/registry.py` is the only reference, behind a lazy import). The provider
returns an `AuthenticatedUser`, never a `Principal` — organization resolution
and membership verification happen in `api/deps.py` and are identical in every
environment. `DevStubAuthProvider` refuses to construct under
`APP_ENV=production`. Identity comes from the `Authorization` header only; no
endpoint accepts a user or organization id in a request body.

**Authorization.** `Principal.role` is populated from the `memberships` row and
carried on every request, but nothing enforces it — as agreed. No endpoint
assumes a permission that does not exist: every handler's only check is
membership, which is genuinely enforced. Role-based checks have an obvious
single insertion point (a dependency alongside `get_principal`).

**Input validation.** All bodies are Pydantic models with `extra="forbid"` and
explicit length limits; path parameters are parsed as UUIDs; `limit` is bounded
`1..100` by FastAPI and re-clamped in the repository. The error envelope is
uniform, carries a `request_id`, and the catch-all handler returns a fixed
string rather than an exception message. `X-Request-Id` is honoured inbound and
returned on every response.

**Storage path traversal.** Keys must match a strict segment pattern
(`[A-Za-z0-9_-]` with dots, joined by `/`), `..` is rejected explicitly, leading
slashes and backslashes cannot match, and length is capped at 512. After
validation the resolved path is re-checked with `is_relative_to(root)`, which
also defeats a symlink pointing outside. Error messages quote the key, never the
resolved filesystem path or the storage root. Writes go to a temporary file and
are renamed, so no reader sees a partial object; `delete` is idempotent and a
missing object raises a typed `StorageObjectNotFound`.

**Database integrity.** Verified against the live migrated schema: foreign keys
present with deliberate behaviour (`memberships` and `projects` CASCADE from
`organizations`; `projects.created_by` SET NULL so deleting a user does not
delete their projects); `uq_organizations_slug`, `uq_users_email`,
`uq_users_auth_subject` and `uq_memberships_organization_id_user_id` all
present; role CHECK constraint enforced in the database, not only in Python;
every id defaults to `gen_random_uuid()`; all timestamps are `timestamptz` with
`now()` defaults; nullability matches intent (only `description`, `created_by`,
`deleted_at`, `display_name`, `auth_subject` are nullable). Migration 001 was
re-verified to run clean from an empty database and to downgrade to zero tables.

**Secrets and configuration.** No `.env` is tracked; `backend/.env` is ignored.
Every credential field in `.env.example` is empty — only non-secret model names
carry values. No log statement references a token, key, secret or password.
`Settings` fails at startup when a selected provider lacks its credential, and
refuses a live provider under `APP_ENV=test`. The frontend inlines exactly one
value into the browser bundle, `API_BASE_URL`; the built client chunks were
searched for `GEMINI`, `SUPABASE`, `SERVICE_ROLE` and `LEONARDO` and contain
none. The browser talks only to our API.

---

## 5. Fixes made

**A-1** — `app/repositories/organizations.py`. Identity now resolves on
`by_subject(subject)` alone. The email fallback and the null-`auth_subject`
claim are both gone. An email already bound to a different subject raises a
typed `Conflict` (409) instead of silently linking. Email is a profile
attribute; the subject is the identity. Genuine provider migration becomes an
explicit operation rather than something a login performs by accident.

**A-2** — `app/graph/serde.py`. The allowlist is passed to the
`JsonPlusSerializer` **constructor** instead of being merged afterwards, so it
is restrictive unconditionally and independent of any environment variable. The
list is still derived from `app.domain.__all__` rather than hand-written.
`LANGGRAPH_STRICT_MSGPACK=true` is retained in `.env.example` as belt and
braces, but nothing now depends on it.

**Documentation** — `docs/R2_CHECKPOINT_SPIKE.md` claimed the allowlist was in
force when it was not. Corrected, with the reason recorded.

Both fixes are the smallest change that removes the defect. No refactoring,
no redesign, no new abstractions.

---

## 6. Tests added

16 new tests. None exist to raise a count; each pins a specific behaviour that
was wrong or untested.

`backend/tests/integration/test_identity_binding.py` — 8 tests (A-1)
- a known subject returns the same user
- an unknown subject presenting a taken email is refused
- the victim's row and `auth_subject` survive the attempt untouched
- **an attacker does not inherit the victim's memberships** — the consequence
  that made this critical
- a row with a null `auth_subject` is no longer freely claimable
- the same person under a new subject is a conflict, not a silent merge
- a genuinely new subject is still provisioned
- display-name fill-in works, and does not overwrite an existing name

`backend/tests/test_checkpoint_serde.py` — 6 tests (A-2)
- the allowlist is not allow-everything **with the environment variable
  deleted** — the exact condition under which it failed
- it contains `CampaignState` and the domain types
- it excludes what was never declared (`subprocess.Popen`, `os.system`, anything
  from `builtins`)
- `checkpointer_kwargs()` carries the same allowlist
- the list is derived from the domain package, not hand-maintained

`backend/tests/integration/test_api_workspace.py` — 2 tests (coverage gap)
- `PATCH` on another organization's project returns 404
- and leaves the row unmodified

**One existing test was changed, not weakened.**
`test_me_works_before_any_organization_is_chosen` seeded a user whose
`auth_subject` did not match the authenticating subject, and passed only because
of the email fallback that A-1 removed. Its fixture now sets the dev stub's
subject, which is the correct setup. The assertions are unchanged. This is the
documented contract change required by `CLAUDE.md` §5.

---

## 7. Verification results

```
pytest    194 passed, 1 skipped        (was 178 — +16 new, 0 removed)
ruff      All checks passed!
ruff fmt  77 files already formatted
mypy      Success: no issues found in 58 source files   (strict)
```

Targeted runs:

```
tests/test_checkpoint_serde.py                6 passed
tests/integration/test_identity_binding.py    8 passed
tests/integration/test_api_workspace.py      20 passed
tests/integration/test_org_isolation.py      10 passed
tests/integration/test_r2_checkpoint_resume.py 9 passed
```

R-2 re-verified end to end with the restrictive allowlist **and the environment
variable removed** — two processes, real Postgres: zero unregistered-type
warnings, resume from the pending gate, run completed, `BrandProfile`
rehydrated as a model. The tightened allowlist does not break resume.

Migration 001 re-verified: clean from an empty database, and reversible.

No TypeScript run: no frontend code was touched by this audit.

---

## 8. Remaining intentional limitations

Unchanged from the Milestone 1 boundary, and none of them a defect:

- **No production authentication.** The dev stub authenticates every caller as
  one configured identity. It cannot construct under `APP_ENV=production`.
- **No role enforcement.** Roles are stored and carried on the `Principal`;
  nothing checks them. Membership boundaries *are* enforced.
- **No storage API.** `/v1/files` is specified but unimplemented (A-7).
- **No rate limiting, no audit log, no CSRF defence.** The API is
  bearer-token-only with no cookie auth, so CSRF does not apply as built; this
  must be revisited if cookie sessions are ever introduced.
- **`/v1/health` is public** (A-3).
- **Frontend has no automated tests.** Playwright is deferred to Milestone 10.
- **The multi-agent review from the previous session remains incomplete** — 22
  of its 30 agents died on a session limit. This audit covers the security and
  correctness axes by direct inspection; it is not a substitute for the general
  code review of the backend that has still not run.

---

## AUDIT STATUS: FIXED DEFECTS
