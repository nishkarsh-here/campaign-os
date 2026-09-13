# PRODUCT_SPEC.md

## 1. Positioning

**From brainstorm to brand-ready campaign.**

An AI marketing orchestration platform that turns fragmented human ideas, brand
knowledge, creative references and market context into approved, localized,
multi-channel campaign assets.

It behaves like an AI creative *team* — interviewer, strategist, creative
director, prompt engineer, art producer, critic, brand police — not like one
chatbot with an image model attached.

## 1a. Canonical vocabulary

These are the business concepts. Code may use a more specific implementation
name, but the mapping is fixed, documented here, and asserted by a test.

| Canonical concept | Implementation type | What it is |
|---|---|---|
| **CAMPAIGN SPECIFICATION** | `CampaignBrief` (alias: `CampaignSpecification`) | The single source of truth for a campaign: objective, audience, product, key message, region, channels, tone, constraints, CTA. Everything downstream derives from it. |
| **CREATIVE SPECIFICATION** | `CreativeSpecification` | The approved creative plan for one direction: concept, composition, subject, lighting, palette, product and brand integration, negative constraints. |
| **CREATIVE DIRECTION** | `CreativeDirection` | One strategic option a human chooses between. |
| **MODEL PROMPT** | `ModelPrompt` | A disposable build artefact compiled from the Creative Specification for one provider. |
| **BRAND BRAIN** | `BrandProfile` + `BrandKnowledge` | Persistent brand identity, plus what retrieval returns for a given question. |

The class is named `CampaignBrief` because "campaign brief" is what the user
interface, the API and marketing teams call the artefact, and because
`CampaignSpecification` sitting beside `CreativeSpecification` reads as two
halves of one object rather than two stages of a pipeline. **The concept is
Campaign Specification.** `app.domain.CampaignSpecification` is a real exported
alias of the same class, so either name is valid in code and the identity is
executable rather than a claim in prose.

## 2. The problem

A single campaign today crosses a brainstorm doc, a research tab, a strategy
deck, a brand PDF nobody rereads, a moodboard, a prompt someone keeps in Notes,
an image tool, a design file, three Slack approval threads, and a resize request.
Context is lost at every boundary, and brand rules are enforced by whoever
happens to notice.

`campaign-os` keeps one structured campaign object through all of it, and puts
the human at the three decisions that actually need a human.

## 3. What makes it different

| Concept | What it does | Why it is not a feature checkbox |
|---|---|---|
| **Brand Brain** | persistent, retrievable brand knowledge (guidelines, products, claims, do/don't) | every node is brand-aware without the user re-explaining the brand |
| **Campaign Interviewer** | asks only the questions whose answers change the output | replaces a blank prompt box with a conversation that terminates |
| **Reference Intelligence** | learns *style* from uploaded references | style transfer of intent, not copying someone's layout |
| **Creative Director** | 3 genuinely distinct strategic directions with rationale | a choice between ideas, not between four renders of one idea |
| **Prompt Compiler** | Creative Spec -> per-model prompt via adapters | prompts become build artefacts; providers become swappable |
| **Creative Evaluator** | "is this a good creative?" — scored on 9 criteria | ranking, not a wall of images |
| **Brand Guardian** | "is this acceptable for *this brand*?" — PASS / NEEDS_REVISION | governance, separate from taste. This is the enterprise unlock. |
| **Revision loop** | KEEP / CHANGE deltas against the approved spec | feedback refines; it does not restart |
| **Deterministic finisher** | Pillow composes logo, headline, CTA, exports variants | brand-usable output, and 8 channels for one generation |

The differentiator in one line: **governed, resumable, explainable campaign
production with humans at the decision points.**

## 4. Users

| Role | Cares about | Primary surface |
|---|---|---|
| Marketing manager | speed from idea to asset | campaign chat, approvals |
| Designer | creative control, editability | direction cards, editor, variants |
| Brand manager | compliance, consistency | Brand Brain, Brand Guardian, approvals |
| Admin | workspace, members, projects | settings |

Organization -> projects -> campaigns -> assets. Roles exist in the schema from
day one; enforcement stays deliberately thin until the workflow needs it.

## 5. Primary journey

```
login -> workspace -> brand onboarding -> Brand Brain
  -> create campaign -> AI interview -> upload references
  -> reference analysis -> market/regional intelligence
  -> CAMPAIGN BRIEF  (= the brief's "Campaign Specification"; see ARCHITECTURE §3)
  -> 3 creative directions ------------------ [GATE 1: human strategy approval]
  -> creative specification -> model prompts - [GATE 2: human prompt approval]
  -> multi-model generation -> AI evaluation -> Brand Guardian -> ranking
                                             -- [GATE 3: human final selection]
  -> revision loop (optional, returns above)
  -> final asset builder -> channel variants -> export
```

## 6. Delivery ladder

Each level is independently demonstrable. Nothing above blocks anything below.

**Level 1 — minimum acceptable.** Brand info -> campaign input -> AI strategy ->
3 concepts -> one generated creative.

**Level 2 — strong MVP.** Brand onboarding, Brand Brain, interviewer, structured
brief, reference analysis, directions, human approval, prompt generation, image
generation, AI evaluation.

**Level 3 — target product.** LangGraph orchestration, persistent state, approval
gates that survive reload, multi-provider generation, Brand Guardian, revision
loops, campaign history.

**Level 4 — future.** Deeper localization, trend intelligence, preference
learning, collaboration, advanced editor, publishing, performance feedback.
Explicitly may not block delivery.

## 7. Human-in-the-loop gates

| Gate | Reviews | Actions | Resumes into |
|---|---|---|---|
| 1 Strategy | 3 creative directions + rationale + AI recommendation | approve one / reject all / request revision | prompt compiler, or director re-run with feedback |
| 2 Prompt | creative specification + compiled prompts (editable) | approve / edit then approve / request revision | generation router, or compiler re-run |
| 3 Final | generated assets, scores, guardian verdict, ranking | select / regenerate / request changes / edit | final asset builder, or revision loop |

Gates are `interrupt()` points. A gate can be answered a day later, from a
different browser, after a server restart.

## 8. Revision semantics

Feedback is interpreted into an explicit delta against the approved spec, shown
to the user before anything regenerates:

```
"good, but it feels too generic"

KEEP    product · logo · key message · brand colours · approved headline
CHANGE  emotional tone -> specific and grounded
        environment    -> real Maharashtra site context
        composition    -> tighter, human presence
```

Only changed fields recompile. `revision_history` records every delta, so
"go back to version 2" is possible and "what changed and why" is answerable.

## 9. Explainability

Users see a short decision summary, never chain-of-thought:

> **Why Direction 2 is recommended** — strongest fit to the stated objective;
> matches the brand's confident, technical tone; closest to the two references
> you selected; regionally credible for Maharashtra; clear product role.

Every AI artefact carries a `rationale` field written for a human reader.

## 10. Creative Style Explorer

Users express visual taste by picking examples, not by knowing design vocabulary:
Premium · Minimal · Technical · Cinematic · Bold · Festive · Local/Cultural ·
Editorial. Selections become structured `CreativePreferences` that feed the
Creative Director and the Prompt Compiler. Later this becomes preference learning.

## 11. Channel variants

One approved creative, re-composed deterministically:
Instagram post 1:1, story 9:16, LinkedIn 1.91:1, Facebook, web banner,
print poster A3/A4. Strategy and brand elements are preserved; the `LayoutSpec`
geometry changes, **and so may the copy**.

A campaign is one plan expressed differently per channel, not one plan resized:
a story is a tall frame read in a second, a LinkedIn banner is read by someone
evaluating a specification, and the same sentence rarely serves both. So a
channel may carry its own approved headline, subhead and call to action
(`CreativeSpecification.channel_copy`). An absent override inherits the
campaign's own copy, which keeps an override a **diff against the approved
plan** rather than a second plan.

Overrides are approved at the same human gate as the rest of the plan, may only
name channels the Campaign Specification declares, are scanned by the Brand
Guardian like any other approved copy, and are revisable one channel at a time.
The composition editor still refuses to rewrite them — now against that
channel's own approved words.

## 12. Target demo (the thing that must not break)

> "I want to launch a premium product campaign for architects in Maharashtra.
> It should feel modern and trustworthy. Here are two ads I like."

AI asks a few sharp questions -> references analysed -> brand loaded ->
structured brief -> 3 directions -> user approves one -> creative spec ->
user approves -> generation across providers -> evaluation -> Brand Guardian ->
recommendation -> user selects -> final asset -> multi-channel export.

Runs end to end on mock providers with seeded demo data and zero network.

**Built and verified.** `scripts/seed_demo.py` produces exactly this campaign by
running the real services — the interview, both gates, generation, evaluation,
the Guardian, a full revision round and composition — and the walkthrough is
scripted in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). `DEMO_MODE=true` refuses to
start against a live provider, so the "zero network" part is enforced rather
than hoped for.

## 13. Non-goals

Not a Canva competitor. Not a social scheduler. Not a stock library. Not a
general chatbot. Not a model-training platform.
