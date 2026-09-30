# HYPERLOCAL_BENCHMARK.md — the Indian Hyperlocal Campaign Benchmark

> **Every company, brand, product, person, claim and figure in this benchmark
> is fictional.** Mitti & Bean, Nila Living and Aarohan Foods do not exist.
> They were written for this dataset. Nothing here is market research, and no
> claim is a real product claim.

Three fictional companies, three Indian cities, three company sizes, three
industries, nine campaigns. The dataset exists to answer one question:

**Does Campaign OS adapt a campaign to a local market, or does it translate
one?**

Those are different things, and the difference is the product. A translation
pipeline produces correct Malayalam over a photograph lit like Rajasthan and
reports success. This benchmark is built so that failure is visible.

## What it is, in the repository

| | |
|---|---|
| Dataset | `backend/app/benchmark/` — typed, one module per company |
| Test matrix | `backend/app/benchmark/matrix.py` — 12 controlled cases |
| Seed | `backend/scripts/seed_benchmark.py` |
| Tests | `backend/tests/test_benchmark_dataset.py` (67) · `backend/tests/integration/test_benchmark_seed.py` (13) |

```bash
cd backend
uv run python scripts/seed_benchmark.py            # idempotent
uv run python scripts/seed_benchmark.py --reset    # rebuild
```

It needs no API key and calls no provider — not an image model, not a language
model, not an embedding model. It refuses to run against a live provider for
the same reason `seed_demo.py` does.

**It does not touch the Milestone 10 demo.** That lives in `demo-org` under
the brand "Northline Facades". This lives in three organizations whose slugs
begin `benchmark-`, and `--reset` deletes only those. A test asserts it.

### No parallel application

Everything here is expressed in the product's own domain models —
`BrandProfile`, `CampaignBrief`, `CreativeDirection`, `CreativeSpecification`,
`ReferenceAnalysis`, `ChannelCopy`. There is no benchmark schema. The dataset
cannot drift from the contracts it claims to exercise without failing to
import, which is the strongest guarantee available that it is testing the real
system.

The only types the benchmark adds are ones the domain has no field for,
because they are metadata *about a test case* rather than campaign truth:
`LocalMarketContext`, `LanguagePreference`, `CompanySize`, `BenchmarkCase`.

## Why these three companies

Each occupies a corner the other two cannot reach.

### Mitti & Bean — Jaipur, Rajasthan · startup · speciality coffee

**The hardest localisation test in India.** Jaipur has the most recognisable
visual shorthand in the country and that shorthand is almost entirely wrong
for a contemporary coffee brand selling to 22-year-olds. A system that
localises by reaching for the nearest regional signifier fails here *visibly*
— it produces a palace behind a cold brew.

It also tests **code-mixed copy**. Hindi and English are not two audiences
here; they are one audience speaking both in a sentence. "Thoda Thehro." is
not a translation of anything.

And it is the **light-governance** end: a founder approves their own headline,
so the prohibited-claims list has five entries and they are about honesty.

### Nila Living — Kochi, Kerala · mid-size · home and lifestyle

**The company the central argument rests on.** Kerala's usable localisation is
climate and material — monsoon light, humidity, cane, lime plaster — not
motif. This is the case where translation is most obviously insufficient,
because the Malayalam can be perfect and the picture still be from somewhere
else. The naive-versus-hyperlocal comparison below is built on it.

Malayalam **leads**: the campaign is conceived in Malayalam and the English
line is the adaptation, not the reverse.

### Aarohan Foods — Guwahati, Assam · enterprise · FMCG

**The governance stress test, and the national/regional pair.** Aarohan runs
an Assamese regional campaign and a Hindi national one for the same product,
with the same brand and the same claims — and different insight, language,
environment and call to action. That pair is the benchmark's clearest single
statement of what localisation means.

Its prohibited-claims list has nine entries because a regulator wrote them,
not because a founder has taste. The Brand Guardian has real work here, and
the contrast with Mitti & Bean's five is deliberate and asserted by a test.

The Northeast is also where tokenisation is most likely and most damaging.
Assam's shorthand in national advertising is tea gardens and Bihu costume,
deployed by people who have never been. The credible cues are a river, a
winter fog, and a kitchen.

## Why these locations create *different* tests

| City | The localisation lever | The failure it invites |
|---|---|---|
| Jaipur | warm sandstone light, plaster, terracotta | palaces, camels, royal pink and gold |
| Kochi | flat overcast monsoon light, humidity, cane | Kathakali, houseboats, coconut-palm borders |
| Guwahati | river scale, December fog, an ordinary kitchen | tea gardens, Bihu costume, rhinoceros |

The three levers are **different kinds of thing** — light quality, climate,
and scale — which is why the set is a benchmark rather than three variations.
A system that handles one by template will not handle the other two.

Each `LocalMarketContext` carries `credible_cues` *and* `tokenising_cues`. The
refusal list is the load-bearing half: a market context that only says what to
include is a stereotype generator. A test asserts no two cities share a
tokenising cue, and another asserts no campaign ever mentions another city's
tokens — not even as something to avoid, because a borrowed refusal list is
evidence the localisation was generic.

## Localisation dimensions

Roughly ordered by depth. The ordering is the argument: everything below
`language` is what a translation pipeline cannot reach.

1. **Language** — which language, in which script, leading or supporting
2. **Audience insight** — what this audience actually worries about here
3. **Environment** — where the picture is set
4. **Visual mood** — light quality, contrast, colour temperature
5. **Material culture** — the surfaces and objects a local would recognise
6. **Occasion** — festivals and seasons, distinguished from one another
7. **Governance** — what this company is allowed to say
8. **Channel** — which reader, on which surface

## Methodology

Each case in `matrix.py` is a **controlled comparison**: something is held
constant, something is varied, and the benchmark asks what the system does
with the difference. A case that varies everything proves nothing, so every
row names its control explicitly and a test enforces that.

The matrix is typed rather than prose because it is meant to be *run*.
`test_benchmark_dataset.py` walks the rows and asserts the dataset actually
contains the pairs each case claims to compare — which is what stops the
matrix from decaying into an aspirational document.

### The twelve cases

| ID | Dimension | Question |
|---|---|---|
| HL-01 | environment | Same brand and product, two cities — does the environment change? |
| HL-02 | language | Same product, two languages — is the second written or translated? |
| HL-03 | audience insight | Same brand, two audiences — does the insight change or only the wording? |
| HL-04 | governance | Does company size change what the creative may say? |
| HL-05 | material culture | Is locality carried by material, or by motif? |
| HL-06 | visual mood | Does the light change with the place? |
| HL-07 | occasion | Does an occasion campaign avoid the occasion's clichés? |
| HL-08 | occasion | Are two festivals in one state treated as distinct? |
| HL-09 | channel | Does per-channel copy adapt, or merely resize? |
| HL-10 | channel | Does an absent override inherit rather than blank? |
| HL-11 | environment | Is localisation dialled *down* where it does not help? |
| HL-12 | governance | Is brand consistency preserved across locations and audiences? |

HL-11 matters more than its position suggests. Both trade campaigns record
regional considerations amounting to "none" or "functional only". Localising a
specification sheet is noise, and a system that inserts regional cues
everywhere because the brand is regional has misunderstood the job.

## The core comparison: naive versus hyperlocal

Built on Nila Living's `veettil-oru-feeling`.

### Naive localisation

Write in English, translate the strings to Malayalam, reuse the visual,
re-crop per channel.

- Headline: "A Feeling At Home" machine-translated
- Visual: a warm golden-hour living room from a national shoot
- Channels: one frame cropped to 1:1, 9:16, 16:9
- Claims: whatever the English original said

**Why it fails**, in four specific ways:

1. **The light is from another state.** Golden hour is wrong for Kerala, where
   the monsoon light that defines the market is flat, cool and shadowless. The
   copy is correct and the picture is from somewhere else.
2. **Translated idiom reads as imported.** "Veettil Oru Feeling" is how the
   audience speaks. A translation of "A Feeling At Home" is not.
3. **Cropping destroys the type area**, so a headline lands on the subject at
   9:16.
4. **Claims cross a border unchecked.** "Waterproof" is prohibited for this
   brand, and a translation pipeline has no opinion about that.

### Campaign OS hyperlocalisation

Conceive in Malayalam from a local insight; derive environment and light from
the market context; hold the brand's claims and visual rules across every
variant; write per-channel copy for each channel's reader.

- Headline: **മഴ പെയ്യുമ്പോൾ.** — conceived in Malayalam
- Insight: what the audience worries about is how the house feels when it
  rains and eleven people are in it
- Visual: bright flat overcast light, no hard shadow, contemporary Kochi
  apartment, green at the window edge
- Refusals recorded: no Kathakali, no houseboats, no coconut-palm borders,
  **no golden-hour grading**
- Channels: the story shortens the headline; the web banner switches to
  English and names the material, because a specifier reads it
- Claims: "waterproof" and "mould-proof" forbidden in the specification
  itself, so the Guardian checks every variant

### What produces the difference

Not a better prompt. Five structural things:

- **Campaign Specification as source of truth** — region, language and
  occasion are structured fields, not prose to be translated
- **Local market context separating credible from tokenising cues** — so "be
  local" has a direction *and a refusal*
- **Reference Intelligence carrying style without reproducible content** — a
  mood transfers, a design does not (ADR-011)
- **Per-channel copy as a sparse diff** — a channel adapts where it needs to
  and inherits where it does not
- **Brand Guardian checking every override**, not only the default copy

## Evaluation framework

Each case states an `expected_signal` written so that failure is recognisable,
and a `naive_failure` describing what a translation pipeline produces instead.
The assertions fall into four families:

1. **Differentiation** — do two campaigns that should differ actually differ,
   in the structured fields rather than in the prose?
2. **Preservation** — does local context survive into the Creative
   Specification, the artefact generation compiles from? Context named only in
   the brief and lost downstream is localisation that never reaches an image.
3. **Containment** — does each organization see only its own data, and does
   each city's campaign avoid every other city's tokens?
4. **Consistency** — do palettes, claims and ADR-006 hold across every
   campaign regardless of locale?

### What this does not measure

**Creative quality.** Nothing offline can. The benchmark tests whether the
*structure* Campaign OS produces differs correctly across locale, audience and
governance; whether the resulting poster is any good remains a human
judgement, and the dataset is deliberately silent about it.

It also stops before generation. Plates, evaluations and Guardian verdicts are
computed by services from real provider output — seeding them by hand would be
exactly the fake functionality this project has refused to build since M0.

### The seed writes rows, and that was once invisible

Worth stating, because it cost this dataset its own demo. `seed_benchmark.py`
writes through the repositories and **never runs the creative graph**, so there
is no LangGraph checkpoint for any of the nine campaigns. `GET /creative` read
only the checkpoint, so it reported no directions and no specification for all
nine while the database held three approved directions and an approved Creative
Specification each — and the Creative screen the storyline opens at step 3 showed
"No creative routes yet", offering a button that would have replaced the seeded
routes with fresh model output (audit findings HL-1 and HL-2).

`seed_demo.py` does not have this shape: it drives `CreativeStageService.start()`
and therefore leaves a checkpoint, which is why the M10 demo worked throughout
and this did not.

Both are fixed, and the fix is a read rather than a fake run: the service falls
back to the application tables when no checkpoint exists, and starting the stage
on a campaign that already has a direction set reports what is there instead of
rebuilding it. Nothing was added to the seed, because a seeded graph execution
would be precisely the invented result this section refuses. See CLAUDE.md
§9 and `tests/integration/test_creative_row_backed.py`.

## Demo storyline

Roughly ten minutes, entirely offline.

1. **Three organizations, one screen.** Show the brand list in each. Note that
   the same signed-in user sees exactly one brand per organization — the
   isolation is the tenancy model, not a filter.
2. **Mitti & Bean → "Apni Raftaar, Apna Pause".** Open the Campaign
   Specification: region Jaipur, language Hindi + English, and an
   `avoid_restrictions` list naming palaces and folk costume. *The refusal is
   in the data.*
3. **The three Creative Directions.** Different subject, environment,
   composition, camera and lighting — not three phrasings of one idea.
4. **Nila Living → "Veettil Oru Feeling".** Same product category, different
   country of mind. Malayalam headline, monsoon light, and "no golden-hour
   grading" written into the specification.
5. **Put the two specifications side by side.** Same schema, same governance,
   and almost nothing in common. That is the pitch.
6. **Aarohan Foods → the pair.** `apnar-swad-apnar-ghor` (Assamese, kitchen,
   pack hidden at the frame edge) against `ghar-ka-swad` (Hindi, Bengali
   kitchen, pack legible). Same product. Opposite treatment of the pack,
   because outside Assam nobody knows it.
7. **The LinkedIn override.** On the Assamese campaign, the trade channel
   switches to English, changes the message to distribution reach, and changes
   the call to action. A different reader, not a different crop.
8. **Claim governance.** Five prohibited claims for the startup, nine for the
   enterprise, and the specifications carry them as `forbidden_text`.

## What the benchmark found in the product

A benchmark that reports nothing about the system under test is not a
benchmark. Four things surfaced while building this, none of them fixed here:

Three were product-contract defects and have since been fixed; one turned out
to be deliberate design.

- **There was no 4:5 Instagram channel.** ✅ **Fixed.** The brief asked for
  Instagram portrait at 4:5 — the tallest frame the feed shows uncropped, and
  the format most feed creative is built for. `CHANNEL_DIMENSIONS` had
  `instagram_post` at 1:1 and `instagram_story` at 9:16 and nothing between,
  so the first draft of this dataset had to fake 4:5 with the square.
  `Channel.INSTAGRAM_PORTRAIT` now exists at 1080×1350 with its own safe area
  and type scale, and the three feed-led campaigns here target it.
- **`CampaignStatus` and the database had drifted.** ✅ **Fixed.** They were
  never the same vocabulary: `CampaignStatus` is the LangGraph workflow's and
  is checkpointed as JSON, while the `campaigns.status` column tracks the
  narrower discovery lifecycle of the row. The column's vocabulary is now its
  own enum, `CampaignRecordStatus`, the check constraint is generated from it,
  and a test asserts the database accepts every member and no others. No
  migration was needed — the database was right all along.
- **`MembershipRepository.grant` reported every integrity error as "already a
  member".** ✅ **Fixed.** A role violating the lowercase `role_valid` check
  surfaced as a membership conflict, which is how an hour goes missing. The
  role is now validated before the insert with the allowed values in the
  error, and the handler distinguishes duplicate membership (`Conflict`),
  invalid role (`ValidationFailed`) and missing user or organization
  (`NotFound`). Anything unrecognised stays a plain `AppError` carrying the
  constraint name, because a wrong label is worse than a vague one.
- **Per-channel copy cannot drop a line — and that is deliberate.** Not a
  defect, so not changed. `ChannelCopy` uses `None` for "inherit", so no value
  means "this channel has no subhead"; `copy_for` documents line removal as a
  geometry decision the layout makes when there is no room. The first draft of
  this dataset assumed otherwise and shipped several silent no-op overrides. A
  test now pins the real contract, and the dataset's overrides all say
  something.

## Dataset at a glance

| Company | City | Size | Industry | Languages | Campaigns |
|---|---|---|---|---|---|
| Mitti & Bean | Jaipur, Rajasthan | startup | speciality coffee | Hindi + English | 3 |
| Nila Living | Kochi, Kerala | mid-size | home and lifestyle | Malayalam + English | 3 |
| Aarohan Foods | Guwahati, Assam | enterprise | FMCG packaged foods | Assamese + Hindi + English | 3 |

Per company: 1 Brand Profile with voice, palette, typography, products,
approved and prohibited claims, visual dos and don'ts, logo rules and a legal
line; 3 abstract style references; a local market context; language
preferences; and 3 campaigns, each with a Campaign Specification, 3 Creative
Directions and an approved Creative Specification carrying per-channel copy.
