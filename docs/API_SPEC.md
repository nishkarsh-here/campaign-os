# API_SPEC.md

FastAPI, JSON over HTTP, versioned at `/v1`. The OpenAPI schema at
`/v1/openapi.json` is authoritative and generates the frontend's TypeScript
types (ADR-010). This document explains intent and the parts a schema cannot
express — status semantics, resume behaviour, idempotency.

## Conventions

- **Auth:** `Authorization: Bearer <token>`. In development `AUTH_PROVIDER=dev_stub`
  resolves a seeded user/org so the app runs without an IdP. The route layer never
  reads the raw token; it receives a resolved `Principal`.
- **Scope:** every resource is org-scoped. A resource in another org returns
  `404`, never `403` — existence is not leaked.
- **Errors:** one shape, always.

  ```json
  { "error": { "code": "VALIDATION_FAILED",
               "message": "Human-readable, safe to display.",
               "details": { "field": "channels" },
               "request_id": "01J..." } }
  ```

  Every code a client can actually receive, and no others — this list used to
  name two that nothing could emit (`RATE_LIMITED`, `GRAPH_ERROR`) and omit six
  that it did:

  | Code | When |
  |---|---|
  | `VALIDATION_FAILED` | bad input, or a refused edit. The `message` is a sentence to show as-is |
  | `UNAUTHENTICATED` | no credential, or one the identity provider rejected |
  | `FORBIDDEN` | a member whose **role** lacks the capability, or no membership at all. `details.required_capability` names what was needed |
  | `NOT_FOUND` | absent, **or in another organization** — existence is not leaked |
  | `CONFLICT` | a state that forbids the action: a gate that is not open, a second open revision, retrying a success, replacing approved creative |
  | `PROVIDER_ERROR` | a vendor failed in a way with no more specific code |
  | `PROVIDER_UNAVAILABLE` | the vendor is down or unreachable |
  | `PROVIDER_TIMEOUT` | the vendor did not answer in time |
  | `PROVIDER_RATE_LIMITED` | the vendor throttled us. **Not** `RATE_LIMITED`: this API does not rate-limit its own callers, so a code implying it would be a fiction |
  | `PROVIDER_INVALID_RESPONSE` | the vendor answered, and the answer would not validate |
  | `CONTENT_BLOCKED` | the vendor's safety filter refused. A client has to handle this: it is a normal outcome, not a bug |
  | `INVALID_STORAGE_KEY` | a malformed key reached the storage layer. Never from a request — no route takes a key (§Files) |
  | `STORAGE_OBJECT_NOT_FOUND` | the row exists and its bytes do not |
  | `INTERNAL` | anything unhandled |

  Provider errors surface a user-safe message and keep vendor detail in logs,
  redacted by shape in `ProviderError.__init__`.
- **Idempotency:** **derived server-side, not supplied by the client.** There is
  no `Idempotency-Key` header and none is read; an earlier draft of this document
  specified one, which no route ever implemented. What exists is stronger.
  `generation_jobs.idempotency_key` is computed from
  `(model_prompt, provider, model, attempt)` and is `UNIQUE`, so replaying
  `POST /generation/start` finds the existing job and charges the provider once
  — from any client, including one that sends nothing. The attempt number is part
  of the key, so a *deliberate* retry is allowed where a *replay* is not.
  `POST /composition` is likewise idempotent per channel, and both creative-gate
  endpoints refuse a gate that is not open rather than re-running it.
- **Lists:** the organization-level lists take `?limit=&cursor=` and answer
  `{ "items": [...], "next_cursor": null }` — `/v1/projects`, `/v1/brands` and
  `/v1/campaigns`. Keyset on the column each one is already sorted by, so the
  order a screen has is the order the cursor walks; `limit` defaults to 50 and is
  capped at 100. **Campaign-scoped lists are not paged** and return every row:
  references, documents, assets, evaluations, guardian results, revisions and
  final assets are bounded by one campaign's own work, and a cursor there would
  be a knob with nothing behind it.
- **Long work is never awaited in a request.** Mutations that start work return
  `202` with a job resource to poll (§Polling contract).

---

## Authorization

**Enforced on the server.** Until the M11 audit it was not: `memberships.role`
had five values, `get_principal` resolved one into every `Principal`, and nothing
read it — so every mutating route accepted a `viewer` exactly as it accepted an
`admin`, and the interface's hidden controls protected nothing (audit finding
A-1). `app/api/authz.py` is now the authority and
`frontend/src/lib/capabilities.ts` is its mirror; a test asserts they agree.

| Capability | Covers |
|---|---|
| `edit_campaign` | create and edit campaigns, briefs, references, preferences and creative plans; start generation, evaluation, brand checks, composition and render |
| `request_revision` | ask for another round — `POST /revision`, `PATCH /revision/delta`, and a `REQUEST_REVISION` or `EDIT` decision at either creative gate |
| `approve` | pass a gate — `APPROVE`/`REJECT` at either creative gate, `POST /revision/approve`, `/approve-delta`, `/reject`, and `POST /evaluation/select` |
| `edit_brand` | everything under `/v1/brands` that writes, including accepting an extracted fact |
| `manage_workspace` | create and change projects |

| Role | Capabilities |
|---|---|
| `admin` | all five |
| `brand_manager` | `edit_campaign` `request_revision` `approve` `edit_brand` |
| `marketing` | `edit_campaign` `request_revision` `approve` |
| `designer` | `edit_campaign` `request_revision` |
| `viewer` | none — reads only |

**A designer cannot approve their own work.** That is the separation the approval
gates exist to create, and it is why `request_revision` and `approve` are
different capabilities rather than one "decide".

**Both creative gates check the decision, not the route.** `POST
/creative/strategy` and `POST /creative/specification/decide` each carry a
decision that is either an approval or a revision request, so the capability is
resolved from the body. One route-level check would either hand a designer the
approval or take away the revision request.

**Reads are not restricted by role.** A `viewer` may read everything in their
organization; that is what the role is for.

**Authorization narrows tenancy; it never replaces it.** Membership is resolved
first, and every repository still filters by organization on every read and
write. So the two refusals mean different things: a **`403`** says the caller
belongs here and lacks the right — `details.required_capability` names it — and a
**`404`** says the organization or row is not theirs, because there existence is
the thing being protected.

---

## Workspace

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/health` | process, database and providers. The only unauthenticated route. See DEPLOYMENT §2 |
| `GET` | `/v1/me` | principal, orgs, memberships, and the caller's **role** in each |
| `POST` | `/v1/organizations` | creates one and makes the caller its `admin`. The only route with no organization scope, because it establishes one |
| `GET` | `/v1/organizations/current` | the organization this request acts in |
| `GET` | `/v1/projects` | `?limit=&cursor=` -> `{items, next_cursor}` |
| `POST` | `/v1/projects` | needs `manage_workspace` |
| `GET/PATCH/DELETE` | `/v1/projects/{id}` | delete is soft. `PATCH`/`DELETE` need `manage_workspace` |

There is no `GET /v1/organizations` listing every organization. `GET /v1/me`
carries the caller's memberships, which is the only answer that is theirs to
have.

## Brand Brain

Every mutating route here needs the `edit_brand` capability (§Authorization).

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/brands` | `?limit=&cursor=`, alphabetical |
| `POST` | `/v1/brands` | create profile from onboarding form |
| `GET/PATCH/DELETE` | `/v1/brands/{id}` | validated `BrandProfile` payload; delete is soft |
| `GET` | `/v1/brands/{id}/brain` | the Brand Brain panel: confirmed / inferred / unknown field status, documents and facts in one call |
| `GET` | `/v1/brands/{id}/assets` | logo, product and font assets, each with a signed `url` |
| `POST` | `/v1/brands/{id}/assets` | multipart; logo/product/font. MIME + magic-byte + size checked |
| `GET` | `/v1/brands/{id}/assets/{asset_id}/content` | the bytes — see **Media URLs** |
| `GET` | `/v1/brands/{id}/documents` | every document with its ingestion status |
| `POST` | `/v1/brands/{id}/documents` | multipart PDF or `{url}`; returns `202` + document with `status=PENDING` |
| `POST` | `/v1/brands/{id}/documents/text` | `{title, text}` for pasted copy |
| `GET` | `/v1/brands/{id}/documents/{doc_id}` | poll ingestion status |
| `GET` | `/v1/brands/{id}/facts` | extracted facts awaiting a human decision |
| `PATCH` | `/v1/brands/{id}/facts/{fact_id}` | accept or reject one. **Only this makes a fact brand truth** — extraction output is never merged into the profile |
| `POST` | `/v1/brands/{id}/knowledge/query` | `{query, k}` -> retrieved chunks + scores. A `POST` that reads, so it needs no capability |

## Campaigns

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/campaigns` | `{brand_id, title, project_id?}`. Needs `edit_campaign` |
| `GET` | `/v1/campaigns` | `?brand_id=&limit=&cursor=`, newest first |
| `GET` | `/v1/campaigns/{id}` | campaign + status |
| `GET` | `/v1/campaigns/{id}/overview` | **the view model** — one call renders the workspace. See §Campaign overview |

**There is no `/state`, no `/cancel` and no `/runs`.** Earlier drafts of this
document specified a generic run resource and a single view-model endpoint; what
was built is one read and one mutation per stage, because each stage has
different legal transitions and a different payload, and a generic `/runs`
response could not say what any of them meant. `GET /overview` is the one call
that renders a whole campaign, and the stage endpoints below are what advance it.

A campaign is not cancellable. Nothing long-running belongs to a campaign as a
whole: generation, evaluation and brand checks are database-backed jobs
(ADR-012), each with its own explicit status, and there is no single execution to
stop.

### Discovery — the interview

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/campaigns/{id}/discovery/start` | begins or resumes the interview -> `DiscoveryTurn` |
| `POST` | `/v1/campaigns/{id}/discovery/answer` | `{answer}` — the user's reply, which resumes the interviewer's interrupt -> `DiscoveryTurn` |
| `GET` | `/v1/campaigns/{id}/conversation` | the transcript |
| `GET` | `/v1/campaigns/{id}/specification` | the Campaign Specification (`CampaignBrief`) — the source of truth |
| `PATCH` | `/v1/campaigns/{id}/specification` | a human edit, marked `edited_by_human` on the field's assertion so recompilation cannot undo it |
| `POST` | `/v1/campaigns/{id}/specification/confirm` | the human confirms the brief. `409` once confirmed, so `discovery/start` also answers `409` after that — a confirmed brief is read with `GET /specification`, not re-interviewed |

`DiscoveryTurn` carries the question in play, what is still missing, and the
specification as it stands. `thread_id` comes from the scope-checked campaign
row, never from a request parameter (M1_SECURITY_AUDIT A-5).

There is no `/messages` pair. An earlier draft specified `GET/POST
/v1/campaigns/{id}/messages`; the transcript is read from `/conversation` and an
answer is posted to `/discovery/answer`, because posting a reply and reading
history are different operations against different state and one collection
resource made them look like appends to the same list.

### Preferences and references

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/campaigns/{id}/preferences/options` | the choices the picker offers |
| `GET/PUT` | `/v1/campaigns/{id}/preferences` | the campaign's visual preferences. `PUT` because it is one whole document |
| `GET` | `/v1/campaigns/{id}/references` | every reference with its analysis and status |
| `POST` | `/v1/campaigns/{id}/references` | multipart images; `202`, analysis async |
| `POST` | `/v1/campaigns/{id}/references/{ref_id}/analyze` | run or re-run the analysis |
| `POST` | `/v1/campaigns/{id}/references/{ref_id}/accept` | accept the analysis into the creative context |
| `GET` | `/v1/campaigns/{id}/references/{ref_id}/content` | the image bytes — see **Media URLs** |
| `GET` | `/v1/campaigns/{id}/creative-context` | what the Creative Director will be given: brand rules, market, preferences and reference style, assembled in one place |

A reference cannot be deleted. Its analysis feeds a `CreativeContext` that a
Creative Specification was built from, so removing one would leave approved work
citing something that is no longer there.

### Approval gates

| Gate | Allowed decisions |
|---|---|
| `strategy` | `APPROVE` `REJECT` `REQUEST_REVISION` |
| `specification` | `APPROVE` `EDIT` `REQUEST_REVISION` |
| `final` | `SELECT` `REGENERATE` `REQUEST_CHANGES` |

The second gate was called `prompt` while it was still a plan. Milestone 5
renamed it to `specification`: what a human approves is the execution plan, and
the model-specific prompt is a rendering of that plan produced later
(`Gate.SPECIFICATION`, PRODUCT_SPEC §1a).

#### Creative stage — implemented in Milestone 5

Per-gate endpoints rather than one generic `/approvals` route. A gate's legal
decisions differ, its payload differs (`direction_id` matters only at the first
gate), and its response differs — one endpoint would have validated all three
in the handler instead of in the schema.

```
GET   /v1/campaigns/{id}/creative                     -> CreativeStageView
POST  /v1/campaigns/{id}/creative/start               -> CreativeStageView
POST  /v1/campaigns/{id}/creative/strategy            -> CreativeStageView
      { decision, direction_id?, feedback? }
PATCH /v1/campaigns/{id}/creative/specification       -> CreativeSpecification
      { any editable specification field }
POST  /v1/campaigns/{id}/creative/specification/decide -> CreativeStageView
      { decision, feedback? }
```

`CreativeStageView` answers "where does this stand" in one call: `gate`
(`strategy_gate` | `specification_gate` | `null`), `direction_set`,
`selected_direction_id`, `specification`, `diversity`, `approved`, `gaps`.

`start` is safe to call again — an existing stage resumes from its checkpoint
rather than regenerating. Answering a gate that is not pending is `400` with
the decisions that *are* legal there; the campaign must be
`SPECIFICATION_CONFIRMED` before the stage can start, or `409`.

A `PATCH` marks each edited field in `human_edited_fields`, and a later
regeneration reproduces those fields verbatim. Editing does not close the gate:
the specification can be edited repeatedly and then approved.

Milestone 5 stops at the approved specification. Nothing is generated on
approval; Milestone 6 reads the approved row.

The generic `POST /v1/campaigns/{id}/approvals` above remains the sketch for
the `final` gate, which Milestone 8 owns.

#### Generation — implemented in Milestone 6

```
GET   /v1/campaigns/{id}/generation                  -> GenerationView
POST  /v1/campaigns/{id}/generation/compile          -> GenerationView
POST  /v1/campaigns/{id}/generation/start            -> 202 GenerationView
POST  /v1/campaigns/{id}/generation/jobs/{job}/retry -> 202 GenerationView
GET   /v1/campaigns/{id}/assets                      -> GenerationView
GET   /v1/campaigns/{id}/assets/{asset}              -> GeneratedAssetView
GET   /v1/campaigns/{id}/assets/{asset}/content      -> image bytes
```

`start` returns **202 with every job still `PENDING`**. The providers are called
after the response is sent, so the request never blocks on an image model; the
client polls `GET /generation` until `complete` is true (§Polling contract).
`GET /assets` returns the same shape so one client type covers both — an asset
always arrives with the job that produced it.

`compile` is separate from `start` on purpose: it produces the canonical prompt
and one prompt per provider without spending anything, so what a provider will
be asked can be read first.

Generation requires an **approved** Creative Specification. Without one,
`GET /generation` reports `can_generate: false` with a `blocked_reason`, and
`start` is `409`. Retrying anything but a failed job is also `409` — re-running
a success would pay twice for an image already in the gallery.

Generation is **API-only** (ADR-015): the server calls a remote provider and
receives bytes. No model runs on the application host. A completed plate
carries its provenance — provider, model, provider request id, latency,
requested aspect ratio and image size, requested and *returned* MIME type,
and the reference-image count. The returned type is read from the bytes, so
`image/png`, `image/jpeg` and `image/webp` are all handled and a row never
claims a format its payload contradicts.

A provider failure produces a normalized `FAILED` job with a user-safe
`error_message` and a stable code — never a crashed workflow, and never a
partial batch reported as a whole one. At most `IMAGE_MAX_RETRIES` extra
attempts are made, and only for a timeout, a rate limit or a 5xx.

Never returned: provider credentials, raw provider payloads, tracebacks, or a
`ModelPrompt`'s `parameters` (provider-specific and opaque outside
`app/providers/`). A failed job carries a user-safe `error_message` and a stable
`error_code`.

Asset bytes are served by the API, never by a storage URL: the key comes from a
row already checked for organization *and* campaign, so an asset id from one
campaign cannot be read through another campaign's URL. The `url` field carries
a short-lived signature — see **Media URLs** below — because an `<img src>`
cannot send the scope headers.

#### Evaluation and selection — implemented in Milestone 7

```
GET   /v1/campaigns/{id}/evaluation                  -> EvaluationView
POST  /v1/campaigns/{id}/evaluation/start            -> 202 EvaluationView
      { asset_ids?: [...] }          // omit to evaluate everything
POST  /v1/campaigns/{id}/evaluation/{eval}/retry     -> 202 EvaluationView
POST  /v1/campaigns/{id}/evaluation/select           -> EvaluationView
      { generated_asset_id, note? }
```

`start` returns **202 with every evaluation still `PENDING`** — a multimodal
call per asset is too slow to hold a request open. The client polls
`GET /evaluation` until `in_flight` is zero (§Polling contract).

`EvaluationView` carries the ranking, the recommendation, **and every
evaluation row including failures**. A fully failed batch must not be
indistinguishable from one that never started: each failed row arrives with a
user-safe `error_message`, a stable `error_code` and `can_retry: true`.

Scores are dimension-by-dimension with the weight that produced them, plus the
`disposition_reasons` — the threshold rules, in words — so a verdict can always
be argued with. Retrying anything but a failed evaluation is `409`.

`select` records the human's choice and accepts **any** asset in the campaign,
evaluated or not: the ranking is advice, and a person who disagrees with it is
still the decision-maker.

Never returned: raw model output, reasoning traces, provider payloads or
credentials — only the short user-facing `rationale`, `strengths` and
`concerns`.

#### Brand Guardian and revision — implemented in Milestone 8

```
GET   /v1/campaigns/{id}/guardian                 -> GuardianView
POST  /v1/campaigns/{id}/guardian/start           -> 202 GuardianView
      { asset_ids?: [...] }
POST  /v1/campaigns/{id}/guardian/{result}/retry  -> 202 GuardianView

GET   /v1/campaigns/{id}/revision                 -> RevisionView
POST  /v1/campaigns/{id}/revision                 -> 201 RevisionView
      { feedback, source_asset_id? }
PATCH /v1/campaigns/{id}/revision/delta           -> RevisionView
POST  /v1/campaigns/{id}/revision/approve-delta   -> RevisionView   // gate 1
POST  /v1/campaigns/{id}/revision/approve         -> RevisionView   // gate 2
POST  /v1/campaigns/{id}/revision/reject          -> RevisionView
```

The guardian follows the same async shape as evaluation: `202` with every check
`PENDING`, polled until `in_flight` is zero. A verdict always arrives with the
checks behind it, each flagged `deterministic` or not — "we matched a prohibited
claim" and "a model thought so" are different kinds of statement, and the UI
says which. A failed check reports `verdict: null`, never a pass.

Revision is two gates, and neither can be skipped. `POST /revision` returns a
*proposal*: nothing has changed yet, and `to_version` is null.
`approve-delta` applies it and creates the next Creative Specification version;
`approve` approves that version, after which the existing
`POST /generation/start` regenerates from it. Milestone 8 adds no second
generation path.

Feedback too vague to act on returns `400` asking for more, rather than a
confident revision of something nobody requested. A `PATCH` of the delta is
re-validated server-side: an edit must not become the way around the locked
fields, and it cannot grant itself an unlock the user's words did not.

Only one revision may be open per campaign (`409`) — two proposals against the
same version would race to become the next one.

### Artefacts — where each one is actually read

There is no per-artefact endpoint. Each artefact is carried by the stage view
that owns it, because a stage's artefact is only meaningful with the state around
it — a direction set without its gate, or a prompt without the job that used it,
invites the reader to draw a conclusion the row does not support.

| Artefact | Read from |
|---|---|
| Campaign Specification (`CampaignBrief`) | `GET /v1/campaigns/{id}/specification` |
| Creative Directions, and which was chosen | `GET /v1/campaigns/{id}/creative` -> `direction_set` |
| Creative Specification | `GET /v1/campaigns/{id}/creative` -> `specification` |
| Compiled prompts | `GET /v1/campaigns/{id}/generation` — with the job each one produced |
| Generated plates | `GET /v1/campaigns/{id}/assets` (same `GenerationView` shape) |
| Evaluations and the ranking | `GET /v1/campaigns/{id}/evaluation` |
| Guardian results | `GET /v1/campaigns/{id}/guardian` |
| Revision deltas | `GET /v1/campaigns/{id}/revision` |
| Layouts and renders | `GET /v1/campaigns/{id}/composition`, `GET /v1/campaigns/{id}/final-assets` |

Earlier drafts listed `/brief`, `/directions`, `/prompts` and `/revisions`. None
was built; the columns above are where those artefacts live.

### Per-channel creative copy

`PATCH /v1/campaigns/{id}/creative/specification` accepts `channel_copy`, a map
of `Channel -> {headline?, subhead?, cta?}`. Every leaf is optional and means
"override this one"; an absent leaf inherits the specification's default, so an
override is a **diff** against the approved plan rather than a second plan.

* Only channels the **Campaign Specification** declares are accepted. Anything
  else is a `400` naming the channels that are allowed.
* Sent whole rather than per channel — it is a small map, and a partial patch of
  a nested map is ambiguous about deletion.
* Subject to the **same Gate 2 approval** as every other field. An unapproved
  draft never reaches composition.
* `GET /v1/campaigns/{id}/creative` returns `channels`, the declared list, so
  the interface only offers what the campaign actually runs.

A revision addresses one channel at a time by a dotted field name —
`channel_copy.instagram_story.headline`. A per-channel call to action is locked
exactly as the default one is and needs an explicit unlock. The map as a whole
cannot be revised as prose.

**The composition editor still refuses to rewrite a call to action**, now
checked against the channel's *own* approved words rather than the default.

### Campaign overview

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/campaigns/{id}/overview` | the command centre: every stage, its state and a sentence, plus versions, the recommendation, the Guardian verdict and the final assets |

A **read model**. It stores nothing and computes no state of its own — each
field is read from the service that owns it, so the overview cannot drift from
the screens it summarises. The one thing it adds is ordering: the stages in the
sequence the product runs them, and one `next_stage` saying what is outstanding.

### Final composition and export

The layout is the thing you change; the image is what you get. Every mutating
call here writes a **new version** — nothing is overwritten.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/campaigns/{id}/composition?channel=` | current `LayoutSpec`, its geometry report, every final asset, and which channels are composed |
| `POST` | `/v1/campaigns/{id}/composition` | `{channel}` -> `201`. Builds the default layout from the approved specification, the selected plate and the brand logo. Idempotent: a channel that already has a layout keeps it |
| `POST` | `/v1/campaigns/{id}/composition/variants` | `{channel, source}` -> `201`. A re-layout of an existing composition, not a regeneration — no model is called |
| `PATCH` | `/v1/campaigns/{id}/composition?channel=` | a constrained edit -> a new layout version. `400` with a readable sentence when refused |
| `POST` | `/v1/campaigns/{id}/composition/render` | `{channel, format}` -> `201` with the new `FinalAssetView`. Synchronous: deterministic Pillow work, no model call, nothing to poll |
| `GET` | `/v1/campaigns/{id}/final-assets` | every render, newest first; `?channel=` to filter |
| `GET` | `/v1/campaigns/{id}/final-assets/{asset_id}` | one asset with its full provenance |
| `GET` | `/v1/campaigns/{id}/final-assets/{asset_id}/content` | the bytes. Use the view's `download_url` for the attachment variant — see **Media URLs** |

**Formats.** `PNG` (default) and `JPEG`. Anything else is a `400`. PDF, print
and A3/A4 production are deliberately out of scope — the print sizes exist in
`CHANNEL_DIMENSIONS` but composing one is refused with a reason, because an RGB
PNG at A3 is not a print deliverable.

**Provenance.** Every `FinalAssetView` carries `kind` (always
`FINAL_BRANDED_ASSET` — a generated plate is a different thing),
`source_asset_id`, `specification_version`, `layout_version`,
`renderer_version`, `version` and `created_at`. A file with no answer to "what
produced this?" is not a deliverable.

**Refusals.** The constrained editor rejects rather than trims: an empty text
element, a rewritten call to action or legal line, a hidden logo, a malformed
colour, a property the element does not have, or a box that would leave the
canvas. Each is a `400` whose `message` is a sentence the interface shows as-is.
A refused edit writes no version at all.

**Storage keys are generated, never derived from input:**
`org-{org}/campaign-{campaign}/final/{channel}-v{version}-{uuid}.{ext}`.

### Files

**There is deliberately no route that takes a storage key from a request.** An
earlier draft of this document specified `GET /v1/files/{storage_key}`; it was
never built, and it should not be. A key in a URL is an object address with no
organization attached, which is exactly the hole the scoped repositories exist
to close.

Every byte-serving endpoint instead resolves a scope-checked row first and reads
*its* key: brand assets, campaign references, generated plates and final assets
each have their own `/content` route under the resource that owns them.
`LocalStorageProvider.signed_url` returns a `local://` reference that is
deliberately not fetchable, so a caller that starts relying on it fails visibly.

### Media URLs

Organization scope is carried by the `X-Organization-Id` header and identity by
`Authorization`. **A browser can send neither on an `<img src>`**, so every
media `url` this API returns also carries a signature:

```
GET /v1/campaigns/{id}/assets/{asset_id}/content?token=<payload>.<signature>
```

The token names the resource kind, the row id, the organization, the user and an
expiry, and is signed server-side (`MEDIA_URL_SECRET`, default lifetime 15
minutes — see `.env.example`). It is minted by the already-authorized request
that returned the view, so nothing extra is fetched to display an image.

Rules for a client:

- **Pass `url` through unchanged.** It has a query string; appending another
  `?` folds your parameter into the token value and the link 404s. Where a
  variant exists the API supplies it as its own field — `FinalAssetView` has
  `download_url` for the `Content-Disposition: attachment` response.
- **Do not store one.** It expires, and it is revoked the moment the user loses
  membership of that organization. Re-read the view to get a fresh one.
- **The headers still work.** A server-side client, a script or `curl` sends
  `Authorization` and `X-Organization-Id` as before and needs no token.

A token grants exactly one row, for a few minutes, to the organization it was
minted in. It carries no storage key: the byte route still loads the row through
the organization-scoped repository and reads the key from *it*. A token
presented for the wrong row, the wrong route, the wrong organization, or after
its expiry is a `404`, and so is a forged one — one answer for all of them,
because distinguishing them would be an oracle for the secret.

## Status vocabulary

Shared by jobs, documents, exports and runs — one vocabulary everywhere:
`PENDING` `RUNNING` `COMPLETED` `FAILED` `CANCELLED`, plus `WAITING_HUMAN` for runs.

## Polling contract

There is no run resource to poll (see §Campaigns). **Each async stage is polled
on its own read endpoint**, and each reports its own "am I still working" field:

| Poll | Until |
|---|---|
| `GET /v1/campaigns/{id}/generation` | `complete` is true |
| `GET /v1/campaigns/{id}/evaluation` | `in_flight` is zero |
| `GET /v1/campaigns/{id}/guardian` | `in_flight` is zero |
| `GET /v1/campaigns/{id}/overview` | no stage is `RUNNING` |
| `GET /v1/brands/{id}/brain` | every document has a terminal status |

**Every 1.5 s, backing off to 5 s after 60 s, and stopping the moment nothing is
in flight** — the command centre polls at 2.5 s because it is a summary rather
than a progress bar. A poller that keeps running against a finished campaign is
a page nobody leaves open, so each one stops rather than slowing down for ever.

SSE remains unbuilt and is not planned: polling cannot silently die, and these
are jobs measured in tens of seconds.
