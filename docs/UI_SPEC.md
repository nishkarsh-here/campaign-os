# UI_SPEC.md

Next.js (App Router) · TypeScript · Tailwind · shadcn/ui.
The product should read as a premium SaaS workspace, not a chat wrapper.

## Design principles

1. **The campaign, not the chat, is the object on screen.** Conversation is one
   panel inside a workspace that also shows the brief, the directions and the
   assets. The user should always be able to see what has been decided.
2. **State is always legible.** Every screen answers: where am I in the process,
   what is the system doing, what is waiting for me.
3. **Approvals look like decisions,** not like form submissions — options,
   consequences, an AI recommendation with reasons, and a visible "you can change
   this later".
4. **Explain, never expose reasoning.** Short rationale text. No thought traces.
5. **Every async surface has four states:** loading (skeleton, never a bare
   spinner), empty (with the action that fills it), error (specific, retryable),
   success. A screen without all four is unfinished.

## Routes

```
/                                     marketing/landing (thin)
/login
/app                                  org switcher, project grid
/app/projects/[projectId]             campaigns list + "New campaign"
/app/projects/[projectId]/brand       Brand Brain: identity, assets, documents, knowledge
/app/campaigns/[campaignId]/overview     the command centre  <- where you land
/app/campaigns/[campaignId]           discovery and the Campaign Specification
/app/campaigns/[campaignId]/inspiration  references, Style DNA, creative context
/app/campaigns/[campaignId]/creative     directions, both human gates, the plan
/app/campaigns/[campaignId]/generate     prompts, provider jobs, the plate gallery
/app/campaigns/[campaignId]/evaluate     scores, ranking, recommendation, selection
/app/campaigns/[campaignId]/refine       brand check, feedback, revision gates
/app/campaigns/[campaignId]/compose      layout, constrained editor, channel variants, export
/app/settings/*                       org, members, providers
```

The command centre is the campaign list's destination, because "where is this
campaign and what is waiting on me?" is the question people actually arrive
with. It is strictly a read model — six stages with a state and a sentence, one
next action, and the numbers that matter — and every card links to the screen
that owns it. It stores nothing, so it can never tell a different story from the
screen behind it. It polls only while a stage is actually running, and stops the
moment none is.

The refine screen asks two questions in order — is this acceptable for the
brand, and what would you change — and shows the answer to the second as a plan
before it runs: KEEP and CHANGE with the current value beside the proposed one.
Approving is the only moment the creative changes, and what runs is exactly
what was on the screen, because applying a delta is a pure function. Feedback
stays natural language; no structured form is required.

The compose screen is arranged around one fact: the layout is the source of
truth and the image is its output. So the render sits *beside* the layout
rather than being the thing you manipulate, and "Render" is an explicit action
— what is on screen is always a file that exists, never an optimistic preview
of one. The layout version and the asset version are shown separately, because
after an edit they legitimately differ until you re-render.

The editor is deliberately small: position, size, visibility, text, alignment,
colour and case, on the elements the composition already has. There is no
drawing, no new element types, no layers panel and no free typography — this is
a composition tool, not a canvas app. Protected controls are visibly disabled
with the reason beside them: the call to action carries an approved campaign
fact, the legal line comes from the Brand Brain, and the logo cannot be hidden.
The server enforces all three independently, so the disabled control is a
courtesy rather than the boundary.

A refused edit is titled "That change was not applied", not "Something went
wrong" — nothing malfunctioned, a rule applied — and the layout on screen
reloads from the server so the two always agree. A layout with a blocking
problem disables the render buttons and lists what is wrong in the user's own
terms, because reporting the problem is strictly better than producing a
broken poster.

Export history is never collapsed to "the latest one". Every render stays
listed with its channel, size, format, layout version, specification version
and timestamp, because a new version must never replace a file someone already
has.

The evaluation screen leads with the recommendation, because that is the
question the user arrived with. Every score is shown beside the sentence that
explains it and the weight that gave it influence, and the threshold rules that
produced a disposition are stated rather than implied — an evaluation a user
cannot interrogate is indistinguishable from a guess. A fully failed batch
renders its failures and retries, never an empty state: "nothing to show" and
"everything broke" must never look the same.

The generation screen polls rather than pushing: 1.5 s while any job is
running, backing off to 5 s after a minute, and stopping entirely once every
job is terminal. No card is ever left spinning — a failed job shows a readable
reason and a retry, because a generation screen that quietly stops updating is
the worst failure it could have.

Discovery, inspiration and creative are separate routes rather than tabs of
one screen. Each is a different kind of work — a conversation, a visual
workspace, a decision — and each is entered at a different time. One route
holding all three would make "what am I being asked to do now" ambiguous, which
is the question a human gate exists to answer.

## The campaign workspace

One route, one persistent layout, content driven by campaign stage:

```
┌──────────────────────────────────────────────────────────────────┐
│ Campaign title · brand chip · status pill      [Cancel] [Export] │
├──────────────────────────────────────────────────────────────────┤
│ Interview › Brief › Directions › Prompt › Generation › Selection │  stepper,
│    ✓          ✓        ● you              ○         ○        ○   │  from
├───────────────────────────┬──────────────────────────────────────┤  node_history
│  CONVERSATION             │  STAGE CANVAS                        │
│  interview turns          │  brief / direction cards / prompt    │
│  reference thumbnails     │  editor / asset grid / comparison    │
│  [message box]            │                                      │
├───────────────────────────┴──────────────────────────────────────┤
│  DECISION BAR — appears only when a gate is pending               │
└──────────────────────────────────────────────────────────────────┘
```

The stepper is backed by `run.node_history`, so progress is real, not decorative.

### Stage canvases

- **Interview** — questions one at a time, each with a "why we ask" hint and a
  skip. Live "what we know so far" chips (audience, region, tone, channel) so the
  user watches structure accumulate. Reference dropzone.
- **Brief** — the structured `CampaignBrief` rendered as a readable document with
  every field labelled and inline-editable. This is the moment the user realises
  the system understood them.
- **Directions** — three cards, equal weight, each with big idea, headline,
  visual idea, rationale, regional note. The recommended one carries a badge and
  an expandable "why". Compare view puts all three side by side.
- **Prompt** — the `CreativeSpecification` as a labelled form (not a text blob),
  with the compiled per-provider prompts in a collapsed "advanced" panel, editable
  by anyone who wants control. Guardian pre-check warnings shown inline.
- **Generation** — a grid of placeholders that fill in as jobs complete. Each tile
  shows provider, status, and on failure a reason plus retry. Partial failure is
  normal and must look normal.
- **Selection** — asset grid with score, guardian verdict badge (PASS / NEEDS
  REVISION / UNKNOWN), rank. Side-by-side comparison of any two. Scores expand
  into the nine criteria. Feedback box feeds the revision loop.
- **Editor** — canvas over the `LayoutSpec`: move/resize elements, edit headline,
  subhead and CTA, swap logo, snap to brand colours, safe-area guides. Server
  render is authoritative; "Render" reconciles.
- **Export** — channel checklist with live aspect previews, then per-variant
  download states.

## Component inventory (shadcn/ui base)

`AppShell` `OrgSwitcher` `ProjectCard` `BrandForm` `BrandAssetUploader`
`DocumentIngestList` `CampaignStepper` `ConversationPanel` `KnownFactsChips`
`ReferenceDropzone` `BriefDocument` `DirectionCard` `DirectionCompare`
`SpecificationForm` `PromptAdvancedPanel` `GuardianBadge` `AssetTile` `AssetGrid`
`AssetCompare` `ScoreBreakdown` `DecisionBar` `RevisionDeltaView` `LayoutCanvas`
`ChannelExportPanel` `StatusPill` `EmptyState` `ErrorState` `SkeletonBlock`

## Data access

- Server Components fetch initial state via `GET /v1/campaigns/{id}/state`.
- One `useCampaignRun(runId)` hook owns polling, backoff and stop conditions
  (API_SPEC §Polling). No component polls on its own.
- Types come from generated `api-types.ts`. Hand-written duplicates are a bug.
- Optimistic UI **only** for local edits (layout, text). Never for approvals or
  generation — those must reflect real server state.

## Accessibility and responsiveness

Keyboard-navigable decisions, visible focus, AA contrast in light and dark,
alt text on generated assets from the creative spec. Desktop-first (this is a
work tool); tablet supported; phone is read-and-approve only.

## Status badges

One tone scale, defined once in `components/states.tsx`: positive, caution,
negative, active, neutral. Every screen was inventing its own emerald/amber/red
classes, which is how "passed" ends up looking different on two pages.

**Colour is never the only signal.** Every badge carries a word as well as a
colour, because a colour-blind reader and a greyscale projector are both real.

## Accessibility

Practical rather than exhaustive: every control has an accessible name (either a
`<label htmlFor>` pair or an `aria-label`), every image has alt text describing
what it *is* rather than "image", errors are announced through `role="alert"`,
and loading regions carry `aria-busy`. No accessibility framework is installed —
the checks are in the markup, where they are cheap to keep true.

## Deliberately out of scope

Real-time multiplayer cursors, a full layer system, freeform vector drawing,
in-app publishing to social networks.
