# Campaign OS — UI/UX Vision

> The design brief for the UI-2 redesign. UI-1 built the token and component
> foundation; this document decides what gets built on it, and why.
>
> It is written against the API that exists. Where the experience this describes
> needs data the backend does not yet return, that is stated in the open, not
> designed around — §12 lists every one of them. A vision document that quietly
> assumes fields is how a redesign discovers in week three that half of it
> cannot be built.

---

## 1. What this product is

Campaign OS turns one brand truth into many local expressions.

```
BRAND  +  MARKET  +  AUDIENCE  →  a campaign that belongs where it runs
```

That sentence is the product. Everything in the interface either serves it or
is decoration. The differentiation is not "AI makes images" — anything makes
images now. It is that the output is *governed* (the Brand Brain says what may
be claimed) and *placed* (the campaign knows it is running in Jaipur in the hot
season, in Hindi and English, for students).

### What it must not feel like

An admin dashboard, a database viewer, a CRUD form stack, a job monitor, or a
chatbot with a text box. The current interface reads as the fourth of those:
thirteen routes, each a list plus a form, with the campaign's journey visible
only as a status word in a table cell.

### The eight questions

A person opening Campaign OS must be able to answer these without
documentation. Every screen in §11 is judged against them.

1. What does this product do?
2. Where do I start?
3. What stage is my campaign in?
4. What has the AI done?
5. What is waiting on me?
6. Why does this output look local?
7. How is my brand being protected?
8. What happens next?

---

## 2. Experience principles

**1. The campaign is a journey, not a record.** The dominant metaphor is
movement through stages, not a row being edited. Navigation shows the whole
path at all times.

**2. Structure is the truth; prose is the rendering.** This mirrors the
architecture (CLAUDE.md §3.1). The interface shows structured, inspectable
facts — region, language, claim, version — rather than paragraphs that assert
them.

**3. AI recommends, a human decides.** Every AI output is attributed and every
irreversible step is a human action. The interface never implies the machine
approved something.

**4. Say the uncertain thing.** A proposed fact is visibly not a confirmed one.
An unevaluated asset is not a low-scoring one. Absence is stated, never
rendered as zero.

**5. No internal vocabulary on the surface.** `CanonicalPrompt`,
`CreativeSpecification`, `VisualPlate` and `CampaignRecordStatus` are
implementation names. They appear only inside an explicitly opened
**Provenance** drawer, where they are the correct and useful words.

| Internal | On screen |
|---|---|
| `CampaignBrief` / discovery | Campaign brief |
| `CreativeDirection` | Creative direction |
| `CreativeSpecification` | Creative plan |
| `CanonicalPrompt` / `ModelPrompt` | *(Provenance drawer only)* |
| `GeneratedAsset` / `VISUAL_PLATE` | Generated visual |
| `BrandGuardianResult` | Brand check |
| `LayoutSpec` | Composition |
| `FinalAsset` | Final campaign asset |

**6. One clear next action per screen.** Never two equally weighted primary
buttons. If the screen cannot say what comes next, it says that instead.

---

## 3. Visual language — "Atlas"

The design language is called **Atlas**, because the product is an atlas of
local campaigns. It is editorial and cartographic, not dashboard-like.

It is deliberately *not* a Linear/Notion/Framer/Canva pastiche. Those are tools
for managing work. This is a tool for making campaigns that belong somewhere,
and the visual identity is built on that idea rather than on a current style.

### The five devices

**1. The Meridian.** The campaign workspace navigation is a single drawn line
with nodes on it — the campaign's journey, made literal. Not tabs. Completed
nodes are filled, the current node is ringed, blocked nodes are hollow and
dashed. Vertical on desktop, horizontal and scrollable on mobile. This is the
product's signature element and its primary answer to "where am I?".

**2. Place stamps.** Market context is set like a cartographic legend — region,
language and season in small letterspaced type, separated by middots, sitting
above or beside the thing they govern.

```
JAIPUR, RAJASTHAN · HINDI + ENGLISH · HOT SEASON, MARCH–JUNE
```

Because it always renders the same way, a person learns to read it at a glance
and stops re-parsing it per screen.

**3. Hairlines, not boxes.** Structure comes from 1px rules and generous space
— the graticule of a map — rather than from nesting bordered cards inside
bordered cards. Shadows are used once, for things that genuinely float.

**4. The Ledger.** Provenance is monospace, small, uppercase: version numbers,
`AI SUGGESTED`, `HUMAN APPROVED`, `BASED ON BRAND BRAIN`, request ids. A
distinct voice for "this is a fact about how we got here" separates it from the
content itself.

**5. Layered sheets.** Depth is `surface → card → raised` plus a hairline, like
overlaid map sheets. Not glassmorphism, not heavy shadow stacks.

### Type and colour

UI-1's tokens are the whole vocabulary — no page-specific values. Inter for
everything, with the `display`/`h1`/`h2`/`h3` steps carrying real hierarchy and
`label` doing the cartographic work. The ember accent is scarce by design: it
marks *you are here* and the single next action, nothing else. When everything
is accented, nothing is.

---

## 4. Information architecture

### Product level

```
/                         Home — the product's argument, and one way in
/app                      Command Center
/app/projects/:id         Project
/app/brands, /:id         Brand Brain
/app/campaigns            All campaigns
/app/campaigns/:id/*      Campaign workspace
/app/signin               Sign in
```

**Command Center** replaces today's bare project list. It answers "what needs
me?" before "what exists": campaigns awaiting a human decision first, then
recent work, then the places to start something new.

### Campaign workspace

Eight destinations, on one persistent Meridian:

| # | Destination | Route | Backing | Ships |
|---|---|---|---|---|
| 1 | Brief | `/campaigns/:id` | `discovery` stage | UI-2A |
| 2 | Inspiration | `/campaigns/:id/inspiration` | real API, **no stage state** | UI-2A |
| 3 | Creative | `/campaigns/:id/creative` | `creative` stage | UI-2A |
| 4 | Generate | `/campaigns/:id/generate` | `generation` stage | UI-2A |
| 5 | Review | `/campaigns/:id/evaluate` | `evaluation` stage | UI-2A |
| 6 | Brand check | `/campaigns/:id/refine` | `guardian` stage | UI-2A |
| 7 | Compose & export | `/campaigns/:id/compose` | `composition` stage | UI-2A |
| — | Local Market | `/campaigns/:id/market` | **derived** — §5 | UI-2C |

Four honesty notes, because the gap between this table and the backend is where
a redesign goes wrong:

- **The backend has six stages**, not seven. `Inspiration` has real endpoints
  but no entry in `CampaignOverview.stages`, so it is declared `optional`:
  always reachable, shown without a fabricated stage state. It enriches a
  campaign rather than gating it.
- **`Local Market` is not on the Meridian yet.** It is the product's defining
  layer and it needs a destination behind it. A node linking to a route that
  does not exist is exactly the fake UI this redesign is under instructions not
  to build, so it joins the rail in UI-2C with a real page.
- **Export is not a stage.** It is the final act of composition, so it shares
  that destination rather than becoming an eighth node with nothing behind it.
- **`/overview` is retained for now.** The plan is that its content merges into
  the workspace landing and the route disappears — but that is a page redesign,
  so it happens in UI-2C. Through UI-2A the route still works; it is simply no
  longer the only way to see stage state, because the Meridian now carries
  that on every screen.

---

## 5. Hyperlocalization as a first-class layer

This is the product's reason to exist and it is currently buried in a form
field. It becomes a visible layer.

### What actually exists

| Concept in the brief | Field | Type | Reality |
|---|---|---|---|
| City / region | `specification.region` | `string \| null` | Free text: `"Jaipur, Rajasthan"` |
| Language | `specification.language` | `string` | One string: `"Hindi + English"` |
| Season / occasion | `specification.timing_occasion` | `string \| null` | `"Hot season, March to June"` |
| Audience | `specification.audience` + `audience_insight` | `string` | Real, rich |
| Local cues | `specification.required_elements` | `string[]` | Real |
| Local restrictions | `specification.avoid_restrictions` | `string[]` | Real |
| Cultural context | — | — | **Does not exist** |
| Multiple markets per campaign | — | — | **Does not exist** — one region per campaign |

So the Jaipur / Kochi / Guwahati panels in the brief are buildable *today*,
from real data, for five of their seven lines. `region` is one free-text string
rather than structured city+state, and `language` is one string rather than a
list — the UI parses them for display but must never pretend they are
structured. Nothing is invented to fill the two gaps.

### How it appears

- A **Local Market destination** on the Meridian showing the full picture:
  place, language, season, audience, the local cues the campaign must include
  and the restrictions it must respect.
- A **place stamp** in the workspace header, on every campaign card, and beside
  every generated asset — so localization is never something you have to
  navigate to in order to remember.
- Local cues and restrictions **cross-referenced** where they bite: beside a
  creative direction, in the brand check, against a final asset.

Multi-market campaigns are a genuine product feature, not a UI feature. They
need a schema change and are out of scope for UI-2 (§12).

---

## 6. Roles — and an honest limit

Five roles exist: `admin`, `brand_manager`, `marketing`, `designer`, `viewer`.
`/me` returns the caller's role per organization.

The frontend models **capabilities**, not roles, so screens ask
`can('approve')` rather than `role === 'admin'` — one place to change when the
vocabulary grows, and no screen inventing its own rule.

| Capability | admin | brand_manager | marketing | designer | viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| View everything | ● | ● | ● | ● | ● |
| Create / edit campaigns | ● | ● | ● | ● | |
| Request revisions | ● | ● | ● | ● | |
| Approve gates | ● | ● | ● | | |
| Edit brand truth | ● | ● | | | |
| Manage projects & members | ● | | | | |

> **This is presentation, not security.** No endpoint currently differentiates
> by role: membership is checked and `Principal.role` is resolved, but a
> `viewer` can call every mutating route the API exposes. Hiding a button
> therefore tidies the interface; it does not protect anything.
>
> The UI is built so that server-side enforcement can land without a redesign —
> the capability map is the same shape the backend needs. Until it does, this
> table describes intent, and no part of the product may claim role-based
> access control. Tracked as audit finding H-5; the fix is a backend change and
> is out of scope for UI-2.

A viewer sees the same information and none of the controls that would fail —
an approve button a person cannot use is worse than no button, because it
teaches them the interface lies.

---

## 7. Motion

Motion explains change. It never decorates.

| Purpose | Behaviour | Duration |
|---|---|---|
| Navigation | Near-instant; content settles rather than flies | 120–160ms |
| Stage advance | The Meridian node fills, the line draws forward | 320ms |
| List entrance | Staggered, ~30ms apart, capped at ~8 items | 200ms each |
| Approval | One deliberate confirmation beat | 400ms |
| Image reveal | Fade from a neutral block, never a spinner-to-pop | 240ms |
| Hover | Depth and border, never movement that shifts layout | 120ms |

Forbidden: bouncing, infinite ambient animation, parallax on scroll-heavy
content, anything that delays a person reaching a control.

**`prefers-reduced-motion` is honoured globally** — already enforced by the
rule UI-1 put in `globals.css`. Under it, every transition becomes an instant
state change. Nothing becomes unavailable and no information is lost.

**On Framer Motion.** UI-2A ships CSS-based motion primitives, because
everything in the table above is a transition or a keyframe and needs no
layout-animation engine. Framer Motion is adopted at the first surface that
genuinely needs orchestrated or shared-element animation — the Home hero
sequence in UI-2B is the expected trigger. Adding a dependency before a
surface needs it is how bundles grow without anyone deciding.

---

## 8. Depth and 3D

Used in at most three places, each lazy-loaded, each optional:

1. **Home hero** — the brand → market → audience → campaign idea, shown rather
   than asserted.
2. **Market visualization** — geography, where it aids comprehension.
3. **Final asset presentation** — the deliverable, presented with weight.

Rules: never on the critical path; the product is fully usable with every 3D
surface failing to load; a static, well-composed fallback ships with each;
nothing 3D is load-bearing for comprehension. WebGL is a garnish here, not an
architecture.

---

## 9. Responsive

Four widths, each designed rather than inherited.

| Width | Shell | Meridian |
|---|---|---|
| 375 | Single column; navigation in a drawer | Horizontal, scrollable, current node centred |
| 768 | Single column, wider gutters; drawer retained | Horizontal |
| 1024 | Persistent left rail | Vertical, compact |
| 1440 | Left rail + room for a context column | Vertical, full labels |

Mobile is a different arrangement, not a narrower desktop. Specifically: the
campaign Meridian becomes a horizontal scroller that keeps the current stage in
view, and the primary action is reachable without scrolling past content.

---

## 10. Accessibility

Everything UI-1 established holds and is not re-litigated: global
`:focus-visible`, skip link, 4.5:1 contrast measured in both themes, status
never by colour alone, labelled controls, `prefers-reduced-motion`.

UI-2 adds:

- **Landmarks and headings that match the IA** — one `h1` per screen, ranks
  that follow the visual hierarchy rather than the font size.
- **The Meridian is a real `<nav>`** with a list, `aria-current="step"` on the
  active node, and stage state in the accessible name — "Generate, blocked" —
  not conveyed by fill alone.
- **Drawers and any dialog** trap focus, close on `Escape`, and return focus to
  the control that opened them.
- **Live regions** for work that completes while the person waits, so a
  finished generation is announced rather than only drawn.
- **Alt text that carries meaning** — a generated visual's alt names its
  direction and market, not "image".

---

## 11. Page-by-page intent

**Home `/`** — The argument, in one screen: one brand, many places. An
interactive example a person can move through, and an unmistakable
*Create campaign*, with *Explore workspace* secondary.

**Command Center `/app`** — Not a project list. First: what is waiting on a
human. Then: campaigns in flight with their place stamps and stage. Then:
brands and projects as places to start. It answers "what needs me?" before
"what exists?".

**Project** — A workspace, not a row. Its brand, its campaigns, the markets it
runs in, recent assets, current activity.

**Brand Brain** — A living brand intelligence surface where trust is visible.
Confirmed, proposed and inferred facts are *visually distinct*, each carrying
its source. This already reflects the architecture — only a human accepting a
fact makes it brand truth — and the interface must make that obvious rather
than showing one undifferentiated list.

**Campaign brief** — A guided conversation that builds a brief, with a live
**Campaign Snapshot** filling in as facts become known, so progress is visible
rather than a form's remaining length.

**Local Market** — §5.

**Creative directions** — Three large visual concepts, comparable side by side,
each stating its idea, its market relevance, and why it differs from the other
two. Not table rows.

**Generate** — "Generating your campaign visuals", with rich per-direction
progress. Provider, model and prompt move into the Provenance drawer, where
they belong and remain available.

**Review** — A creative review workspace: the visual large, scores as
plain-language judgements, risks named. The reasoning is explained, never
dumped.

**Brand check** — A review layer: what passed, what is flagged, why, and the
human decision that follows. The verdict is computed from the checks and the
interface shows that chain.

**Refine** — Change made legible: previous beside current, what changed and
what was deliberately preserved. Version history as an intentional record.

**Compose & export** — A visual canvas showing safe area, headline, CTA, logo
and image, with the deterministic renderer remaining the source of truth. No
brand text moves into the image model (ADR-006), and the layout stays the
document the render comes from (ADR-014). Export presents the deliverable at
size, with its market, channel, version and both approval states.

---

## 12. Out of scope — and why

Named here so they are decisions rather than omissions.

| Wanted | Blocked by | Needed |
|---|---|---|
| Rich project cards (campaign counts, markets, activity) | `Project` returns only id, org, name, description | Backend aggregation, or N+1 client fetches |
| Assets browser as a top-level destination | No cross-campaign asset listing endpoint | New route |
| Insights / Activity feed | No activity or audit-event endpoint | New table + route |
| Multi-market campaigns | One `region` per specification | Schema change |
| Structured city/language | Both are free text | Schema change |
| Cultural-context panel | No such field | Schema change |
| Role-gated *security* | No endpoint checks role | Backend enforcement (H-5) |
| Share / review links | No sharing model | Design + backend |

Where a destination's data does not exist, UI-2 shows an honest empty state
naming what is missing — never a fabricated number. Inventing plausible counts
to make a card look finished is the one failure mode this document exists to
prevent.

---

## 13. Delivery

| Stage | Scope |
|---|---|
| **UI-2A** | Application shell, information architecture, the Meridian, place stamp, capability model, motion foundation |
| UI-2B | Home, Command Center, Projects, Brand Brain |
| UI-2C | Campaign workspace landing (absorbing `/overview`), Local Market |
| UI-2D | Brief as guided conversation, Campaign Snapshot |
| UI-2E | Creative directions, Generate, Review, Brand check |
| UI-2F | Refine, Compose, Export, final asset presentation |

Each stage ends with `vitest`, `tsc`, `next build`, the backend suite, and a
visual inspection at 375 / 768 / 1024 / 1440 in both themes. A stage that
cannot pass those does not end.

### Rules that bind every stage

- Every control calls a real endpoint. No mocked data, no placeholder numbers,
  no invented AI output.
- No backend change without a stated correctness reason.
- Only UI-1 primitives and tokens; a page-specific style is a bug.
- Nothing in `docs/` claims a capability the code does not have.
