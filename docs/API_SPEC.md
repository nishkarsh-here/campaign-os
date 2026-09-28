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

  Codes: `VALIDATION_FAILED` `UNAUTHENTICATED` `FORBIDDEN` `NOT_FOUND`
  `CONFLICT` `RATE_LIMITED` `PROVIDER_ERROR` `PROVIDER_UNAVAILABLE`
  `GRAPH_ERROR` `INTERNAL`. Provider errors surface a user-safe message and
  keep vendor detail in logs.
- **Idempotency:** any endpoint that spends money or starts work accepts
  `Idempotency-Key`. Replaying a key returns the original result.
- **Lists:** `?limit=&cursor=` -> `{ "items": [...], "next_cursor": null }`.
- **Long work is never awaited in a request.** Mutations that start work return
  `202` with a run or job resource to poll.

---

## Workspace

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/me` | principal, orgs, memberships |
| `GET/POST` | `/v1/organizations` | |
| `GET/POST` | `/v1/projects` | `?organization_id=` |
| `GET/PATCH/DELETE` | `/v1/projects/{id}` | delete is soft |

## Brand Brain

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/brands` | create profile from onboarding form |
| `GET/PATCH` | `/v1/brands/{id}` | validated `BrandProfile` payload |
| `POST` | `/v1/brands/{id}/assets` | multipart; logo/product/font. MIME + magic-byte + size checked |
| `GET/DELETE` | `/v1/brands/{id}/assets/{asset_id}` | |
| `POST` | `/v1/brands/{id}/documents` | multipart PDF or `{url}` / `{text}`; returns `202` + document with `status=PENDING` |
| `GET` | `/v1/brands/{id}/documents/{doc_id}` | poll ingestion status |
| `POST` | `/v1/brands/{id}/knowledge/query` | `{query, k}` -> retrieved chunks + scores. Exists for debugging and for the "what does the AI know about us" panel |

## Campaigns

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/campaigns` | `{project_id, brand_id, title, initial_message?}` |
| `GET` | `/v1/campaigns` | `?project_id=&status=` |
| `GET` | `/v1/campaigns/{id}` | campaign + status + current gate |
| `GET` | `/v1/campaigns/{id}/state` | **the view model** — one call renders the whole workspace: brief, directions, spec, prompts, assets, evaluations, guardian, ranking, pending gate |
| `POST` | `/v1/campaigns/{id}/cancel` | terminal `CANCELLED`; no further node runs |

### Running the graph

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/campaigns/{id}/runs` | `202` -> `{run_id, status}`. Starts or continues the graph. Idempotent per campaign: a run already `RUNNING` returns that run |
| `GET` | `/v1/campaigns/{id}/runs/{run_id}` | `{status, current_node, node_history, pending_gate, error}` — drives the progress UI |
| `GET` | `/v1/campaigns/{id}/runs` | history |

`pending_gate` is the interrupt payload:

```json
{ "gate": "strategy",
  "options": ["APPROVE", "REJECT", "REQUEST_REVISION"],
  "payload": { "directions": [...], "recommended_direction_id": "…",
               "recommendation_rationale": "…" } }
```

### Conversation

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/campaigns/{id}/messages` | transcript |
| `POST` | `/v1/campaigns/{id}/messages` | user's interview answer; resumes the interviewer interrupt. `202` + run |

### References

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/campaigns/{id}/references` | multipart images; `202`, analysis async |
| `GET/DELETE` | `/v1/campaigns/{id}/references/{ref_id}` | |

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

### Artefacts

| Method | Path | Notes |
|---|---|---|
| `GET` | `/v1/campaigns/{id}/brief` | latest, `?version=` for history |
| `GET` | `/v1/campaigns/{id}/directions` | |
| `GET` | `/v1/campaigns/{id}/specification` | |
| `GET` | `/v1/campaigns/{id}/prompts` | grouped by provider |
| `GET` | `/v1/campaigns/{id}/assets` | assets + evaluation + guardian verdict + rank |
| `GET` | `/v1/campaigns/{id}/revisions` | KEEP/CHANGE deltas per iteration |

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

The frontend polls `GET /runs/{run_id}` every 1.5 s while `RUNNING`, stops on any
terminal status or `WAITING_HUMAN`, and backs off to 5 s after 60 s. SSE is a
Milestone 10 optimisation; polling is the contract, because polling cannot
silently die.
