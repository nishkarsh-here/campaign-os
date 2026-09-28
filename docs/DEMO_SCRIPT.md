# DEMO_SCRIPT.md — the twenty-minute walkthrough

Everything below runs on **mock providers with no network**. Nothing in this
script can be broken by an expired key, a rate limit or conference wifi. That is
not a convenience; it is why the demo path exists.

## Before you start

```bash
# backend/.env
DEMO_MODE=true
LLM_PROVIDER=mock
IMAGE_PROVIDER=mock
EMBEDDING_PROVIDER=mock
MOCK_FAILURE_MODE=none        # anything else will fail things on purpose
```

```bash
cd backend
uv run alembic upgrade head
uv run python scripts/seed_demo.py --reset     # ~15 seconds
uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

The seed prints the campaign URL. Open it and leave the tab ready.

**Check before you present**: the header shows a **DEMO MODE** badge, the
overview shows five green stages and **one amber "Needs you" on Brand check**,
the Channels card shows three thumbnails, and the three final assets carry three
different headlines. If any of those is missing, re-run the seed with `--reset`.

**The amber stage is the point, not a fault.** The Brand Guardian rejected the
creative the evaluator ranked first. That is the single best moment in this
demo — quality and brand safety are different questions, and here they
disagree. Do not re-seed hoping for a green one; the seed is deterministic and
will produce the same rejection every time.

The seed is idempotent — running it without `--reset` does nothing if the data
is already there — and `--reset` deletes only what the seed created, so your own
work in the same organization survives.

That scoping cuts both ways: the campaigns list will also show anything else in
the database. For a pristine screen, point `DATABASE_URL` at an empty database
(`createdb campaign_os_demo`), migrate, and seed into that. The seed prints the
campaign URL either way, so the walkthrough never depends on picking the right
row out of a list.

---

## The script

Times are cumulative and generous. The whole thing fits in twenty minutes with
questions.

### 1 · The command centre (0:00)

Open `/app/campaigns/<id>/overview`.

> "This is one campaign. Six stages, each with a state and a sentence. Nothing
> on this screen is stored — every number is read from the service that owns it,
> so the dashboard cannot disagree with the screen it summarises."

Point at: **Creative Specification v3**, **1 revision**, **3 channels**, and the
recommendation at **80/100**. The story is already on the screen before you have
opened anything.

Then point at the one stage that is not green — **Brand check · Needs you**,
*"The selected creative was rejected — review the findings."*

> "And this is the interesting one. The evaluator ranked this creative first,
> at eighty out of a hundred. The Brand Guardian then rejected it. Those are
> two different questions — *how good is it* and *is this acceptable for this
> brand* — and the system is allowed to disagree with itself in public rather
> than quietly averaging the two into one number."

Leave it amber. You will come back to it at step 10, and the card at the top
already tells you where to go next.

### 2 · The Brand Brain (2:00)

`Brands → Northline Facades`.

> "Everything downstream reads from here. This document was uploaded, extracted,
> chunked and embedded. The AI proposed these facts — and a human accepted them.
> Model output never becomes brand truth on its own."

Show the palette and the **prohibited claims**. Say that the Guardian will use
them later; do not explain how yet.

### 3 · Discovery and the Campaign Specification (4:00)

Back to the campaign, then **Campaign Specification →**.

> "A LangGraph interview, which consults the Brand Brain before it asks anything
> — so it never asks what it can already work out — and stops on a budget rather
> than going forever."

Show the specification and the **stated / inferred** badges.

> "What I asserted is STATED. What it worked out is INFERRED. Those are never
> collapsed, because a campaign built on a guess you were never told about is
> how this goes wrong."

Point at a field marked **Yours**.

> "I edited this one. It is marked as a human edit, and recompilation cannot
> overwrite it. That is enforced, not a convention."

### 4 · References and creative context (6:00)

**Inspiration**.

> "Three references, analysed for style. The schema has no field that could hold
> reproducible content — no quoted text, no logos, no coordinates, no font names.
> Learn the style, never copy the design."

Show the derived style profile.

> "Nobody typed these weights. They are recomputed on read from what was picked,
> so adding a reference re-weights everything without anyone re-picking."

### 5 · The Creative Director and Gate 1 (8:00)

**Creative**.

> "Three strategic directions. They are checked for genuine distinctness by
> comparing the structured choices with set overlap — not hoped to be different,
> and not clustered by a model, because the answer has to be the same every
> time."

> "This is the first human gate. The system recommends; a person decides."

### 6 · The Creative Specification and Gate 2 (10:00)

> "Approving a direction produces this: the execution plan. Strategy and
> execution are separate decisions with separate gates — collapsing them makes
> the first gate meaningless."

Note that the call to action and key message are **pinned** from the Campaign
Specification, overwritten after the model runs rather than requested from it.

Scroll to **Per-channel copy**.

> "A campaign is one plan expressed differently per channel — not one plan
> resized. A story is a tall frame read in a second; a LinkedIn banner is read
> by someone evaluating a specification. So the story has a shorter headline
> and LinkedIn has its own line and its own call to action."

Point at Instagram post, which has no override.

> "And this one inherits. An override is a diff against the approved plan, not
> a second plan — which is what keeps one campaign one campaign. Only channels
> this campaign actually runs appear here, and these are approved at the same
> gate as everything else. They are not editable in the composition editor."

### 7 · The compiled prompt (11:00)

**Generate**, and expand the prompt.

> "The approved specification compiled into image controls. Deterministically —
> no model call — so it is reproducible from its source. And note what is *not*
> here: no headline, no call to action. The image model is told to leave this
> area quiet and is never asked to render brand text."

### 8 · Generation (12:00)

> "Three plates. Every one is labelled VISUAL_PLATE, in the column, because a
> plate is not a finished creative."

If you want to show failure handling, this is the moment to mention that a
failed job shows a reason and a retry — do not actually break it.

### 9 · Evaluation and the recommendation (13:00)

**Evaluate**.

> "Ten dimensions, scored against the plate's *own* specification version — not
> the latest one, which after a revision is a plan this plate never saw."

Expand a score.

> "The model scored the dimensions. The **code** computed the total and the
> disposition, from published weights and published thresholds. There is nothing
> here for a model to invent, and the object validates that its own total
> follows from its own dimensions."

> "And it is allowed to decline. If everything had been rejected it would say
> so rather than putting the least bad one forward."

Note the one at the top — **#1, 80.3, PASS** — and say that it is the one a
person selected.

> "Hold that thought. The evaluator likes this creative. Ask the Brand Guardian
> the same question in a minute and you get a different answer."

### 10 · The Brand Guardian (15:00)

**Refine**.

> "A different question from 'how good is it?'. This one is: *is this acceptable
> for this brand?* Claim safety, brand restrictions and the palette are decided
> in code against the Brand Brain — not asked of a model."

**This is the payoff.** Six creatives were checked; five passed. The one that
did not is the one the evaluator ranked first and a person selected — verdict
**REJECT**.

Open its checks. Seven of the eight pass. The one that fails is **brand_tone**:

> *"Reads warmer and more consumer than the brand's stated tone."*
> *Suggested fix: cool the palette and remove the lifestyle framing.*

> "Nothing here is a model's opinion about the verdict. The model observed the
> tone; the **code** turned eight checks into REJECT. A model never returns a
> verdict, and a check that fails to *run* leaves the verdict null — an outage
> must never read as brand approval."

> "And notice what the product did with the disagreement. It did not average
> them into one score, and it did not let the higher number win. It put the
> campaign into *Needs you* and said which creative and which rule. A human
> decides whether to revise it, select a different one, or ship it anyway — and
> every one of those is a decision someone made on the record."

If someone asks why the demo is not all green: this is why, and it is the
honest state of this campaign. A product that only ever demonstrates its happy
path has not shown you the part that matters.

### 11 · The revision (16:00)

Show the revision history entry.

> "Someone said the environment should feel more local. That became this: an
> explicit KEEP / CHANGE / ADD / REMOVE plan, shown before anything ran."

> "Approving it produced the next Creative Specification version. **The previous
> one still exists, unchanged, and the assets generated from it still point at
> it.** Applying a revision is a pure function, asserted field by field."

The plan is at **v3** here, not v2: v1 came out of the Creative Director, v2 was
the human edit that added per-channel copy, and v3 is this revision. Three
versions, each a row, none of them overwritten.

### 12 · Final composition (18:00)

**Compose**.

> "Here is the part that matters. The AI made the plate. This layer — the logo,
> the headline, the call to action, the exact brand colours, the safe areas — is
> drawn by deterministic code, because generative models are unreliable at every
> one of those."

Change the headline size, press **Apply**, then **Re-render**.

> "The layout is the source of truth; the image is its output. Editing changed
> data and re-rendered. Note that the layout is now v2 and the asset was still
> v1 until I re-rendered — those are allowed to differ, and the screen says so."

**Now do the deliberate failure.** Set the headline's Left % to 94.

> "And it refuses. 'That change was not applied — that position would put the
> element outside the canvas.' No version was written and no broken poster was
> produced. Every refusal here is a sentence, never a silently ignored control."

### 13 · Channel variants and export (19:00)

> "Three channels, from one composition. A variant is a re-layout — same plate,
> same logo, new geometry. No model is called and nothing is regenerated."

Put the three side by side.

> "And the words differ. The post says *Built to outlast the building it clads*,
> the story says *Outlasts the building*, LinkedIn says *Specified for a 40-year
> facade life* and asks for the FS-9 pack by name. One campaign, three voices —
> and the post is still inheriting the campaign's own line."

Scroll to **Exports**.

> "Every render is kept, with the layout version, the specification version and
> the renderer version that produced it. A new version never replaces a file
> someone already has."

Press **Download**.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Header has no DEMO MODE badge | `DEMO_MODE` not set | set it and restart the API |
| A job sits on "Running" forever | the API restarted mid-job | restart it again; startup marks abandoned jobs failed and the retry button works |
| A screen shows an unexpected failure | `MOCK_FAILURE_MODE` is not `none` | set it to `none` and restart |
| Images do not load | `API_BASE_URL` is not reachable from the browser | it must be an origin the browser can reach, not an internal name |
| Seed says data is already present | it is idempotent | `--reset` to rebuild |
| Brand check shows amber "Needs you" | **expected** — the Guardian rejected the selected creative | nothing to fix; this is step 10 of the script |

## What not to promise

Say these before someone asks, rather than after:

- **Live Gemini reasoning and embeddings are verified; image generation is
  not.** All three adapters are built and covered by tests driving a fake SDK
  client. Against a real key the first two pass their smoke tests; the image
  one does not run at all: image generation is not available on the free tier
  (`429`, *"limit: 0 requests per day"*). A second cause — the adapter asking
  for `image/png`, which no Gemini image model produces — has been fixed, but
  the fix cannot be proven without a billed key. See DEPLOYMENT §9. Mock mode
  is the guaranteed path, by design.
- **Only two vendors are implemented**, `mock` and `gemini`. Leonardo, Tavily
  and Supabase storage are Protocol seams with no adapter behind them;
  selecting one fails at startup rather than degrading quietly.
- **Print output is out of scope.** The layout engine can size an A3 canvas;
  print *production* — CMYK, bleed, crop marks, PDF — is not built, and the API
  refuses a print channel with a reason.
- **The renderer uses a bundled typeface** unless the brand uploaded one. It
  does not identify or substitute a named font.
- **Background work does not survive a restart.** It is reconciled into a
  visible, retryable failure at startup rather than a spinner.
- **The Guardian verdict in this demo is a mock provider's deterministic
  judgement**, derived from the plate's own pixels. It is reproducible and it
  exercises the real decision path — the verdict is still computed in code from
  the checks — but it is not a real model assessing real artwork.
