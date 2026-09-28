"""The hyperlocalisation test matrix.

Each case is a controlled comparison: something is held constant, something is
varied, and the benchmark asks what the system does with the difference. A
case that varies everything proves nothing, so every row here names its
control explicitly.

The matrix is typed rather than prose because it is meant to be *run*, not
only read. `tests/test_benchmark_dataset.py` walks these rows and asserts that
the dataset actually contains the pairs each case claims to compare — which is
what stops the matrix from drifting into an aspirational document.

**A note on what this measures.** These cases test whether the *structure*
Campaign OS produces differs correctly across locale, audience and governance.
They do not measure whether the resulting creative is good; nothing offline
can. Quality remains a human judgement, and the benchmark is deliberately
silent about it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.common import DomainModel


class LocalisationDimension(StrEnum):
    """The axes along which a campaign can be local, in rough order of depth.

    The ordering is the argument: `LANGUAGE` alone is what a translation
    pipeline achieves, and everything below it is what it cannot reach.
    """

    LANGUAGE = "language"
    AUDIENCE_INSIGHT = "audience_insight"
    ENVIRONMENT = "environment"
    VISUAL_MOOD = "visual_mood"
    MATERIAL_CULTURE = "material_culture"
    OCCASION = "occasion"
    GOVERNANCE = "governance"
    CHANNEL = "channel"


class BenchmarkCase(DomainModel):
    """One controlled comparison."""

    case_id: str
    dimension: LocalisationDimension
    #: What the case asks, in one sentence.
    question: str
    #: What must be identical for the comparison to mean anything.
    held_constant: list[str] = Field(min_length=1, max_length=8)
    #: What differs.
    varied: list[str] = Field(min_length=1, max_length=8)
    #: Campaign slugs being compared. Two for a pair, one for a property that
    #: is asserted about a single campaign.
    campaign_slugs: list[str] = Field(min_length=1, max_length=4)
    #: What a correct system produces. Written so failure is recognisable.
    expected_signal: str
    #: What a naive pipeline produces instead, where that differs.
    naive_failure: str = ""


CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="HL-01",
        dimension=LocalisationDimension.ENVIRONMENT,
        question="Same brand and product, two cities — does the environment change?",
        held_constant=["brand", "product", "claims list", "brand voice"],
        varied=["city", "audience insight", "environment", "lighting"],
        campaign_slugs=["apnar-swad-apnar-ghor", "ghar-ka-swad"],
        expected_signal=(
            "The Assamese campaign is set in an Assamese kitchen with the pack "
            "at the frame edge; the Hindi one is set in a Bengali kitchen with "
            "the pack legible. Same product, opposite treatment of the pack."
        ),
        naive_failure="One environment reused with a translated headline over it.",
    ),
    BenchmarkCase(
        case_id="HL-02",
        dimension=LocalisationDimension.LANGUAGE,
        question="Same product, two languages — is the second one written or translated?",
        held_constant=["product", "brand", "key claims"],
        varied=["language", "headline concept", "call to action"],
        campaign_slugs=["apnar-swad-apnar-ghor", "ghar-ka-swad"],
        expected_signal=(
            "The Assamese line leads on familiarity ('the taste your kitchen "
            "knows') and the Hindi line leads on provenance ('from Assam') — "
            "because familiarity does not exist outside Assam. The calls to "
            "action differ too: ASK FOR AAROHAN versus TRY IT ONCE."
        ),
        naive_failure=(
            "'ASK FOR AAROHAN' rendered in Hindi, addressed to people who have never heard of it."
        ),
    ),
    BenchmarkCase(
        case_id="HL-03",
        dimension=LocalisationDimension.AUDIENCE_INSIGHT,
        question="Same brand, two audiences — does the insight change or only the wording?",
        held_constant=["brand", "product family", "visual rules"],
        varied=["audience", "register", "language policy", "channel"],
        campaign_slugs=["veettil-oru-feeling", "specified-not-styled"],
        expected_signal=(
            "The consumer campaign is Malayalam-led and sells a feeling; the "
            "specifier campaign is English-only and sells test data. Same "
            "chair, and the word 'feeling' appears in neither the brief nor "
            "the specification of the second."
        ),
        naive_failure="The consumer campaign re-cropped for LinkedIn.",
    ),
    BenchmarkCase(
        case_id="HL-04",
        dimension=LocalisationDimension.GOVERNANCE,
        question="Does company size change what the creative is allowed to say?",
        held_constant=["category adjacency (both are consumables)", "pipeline"],
        varied=["prohibited claim count", "approval weight"],
        campaign_slugs=["apni-raftaar-apna-pause", "apnar-swad-apnar-ghor"],
        expected_signal=(
            "Mitti & Bean carries five prohibited claims about honesty; "
            "Aarohan carries nine written by a regulator. The Guardian has "
            "materially more to check on the enterprise campaign, and the "
            "enterprise specification names more forbidden text."
        ),
        naive_failure="One claims policy applied to both, tuned to whichever was authored first.",
    ),
    BenchmarkCase(
        case_id="HL-05",
        dimension=LocalisationDimension.MATERIAL_CULTURE,
        question="Is locality carried by material, or by motif?",
        held_constant=["the instruction to be local"],
        varied=["city"],
        campaign_slugs=["apni-raftaar-apna-pause", "veettil-oru-feeling"],
        expected_signal=(
            "Jaipur is carried by sandstone-warm light and raw plaster; Kochi "
            "by flat overcast monsoon light and cane. Neither reaches for a "
            "landmark, and both name the refusal explicitly."
        ),
        naive_failure="A palace behind the coffee and a houseboat behind the chair.",
    ),
    BenchmarkCase(
        case_id="HL-06",
        dimension=LocalisationDimension.VISUAL_MOOD,
        question="Does the light change with the place?",
        held_constant=["premium positioning", "product-led composition"],
        varied=["light quality", "contrast", "colour temperature"],
        campaign_slugs=["apni-raftaar-apna-pause", "veettil-oru-feeling"],
        expected_signal=(
            "Warm raking light with strong falloff in Jaipur; bright flat "
            "overcast with no hard shadow in Kochi. The Kerala brand "
            "explicitly forbids golden-hour grading, which is the Jaipur "
            "brand's default."
        ),
        naive_failure="The same warm cinematic grade applied everywhere.",
    ),
    BenchmarkCase(
        case_id="HL-07",
        dimension=LocalisationDimension.OCCASION,
        question="Does an occasion campaign avoid the occasion's clichés?",
        held_constant=["brand", "product", "visual rules"],
        varied=["occasion", "seasonal mood"],
        campaign_slugs=["onathinu-veedu", "bhogali-r-pise"],
        expected_signal=(
            "Onam is entered through moving furniture before guests arrive; "
            "Magh Bihu through provisioning for a fortnight of cooking. Both "
            "forbid costume and performance, and the pookkalam is permitted "
            "only half-finished at the frame edge."
        ),
        naive_failure="Centred pookkalam, Bihu dancers, and a festival greeting as the headline.",
    ),
    BenchmarkCase(
        case_id="HL-08",
        dimension=LocalisationDimension.OCCASION,
        question="Are two festivals in one state treated as distinct?",
        held_constant=["brand", "region", "language"],
        varied=["festival", "mood"],
        campaign_slugs=["bhogali-r-pise"],
        expected_signal=(
            "The brief names Magh Bihu specifically and records that its mood "
            "is practical where Rongali Bihu's is celebratory. Treating 'Bihu' "
            "as one occasion is itself the failure."
        ),
        naive_failure="'Bihu' handled as a single generic Assamese festival.",
    ),
    BenchmarkCase(
        case_id="HL-09",
        dimension=LocalisationDimension.CHANNEL,
        question="Does per-channel copy adapt, or merely resize?",
        held_constant=["campaign", "approved claims", "brand"],
        varied=["channel", "reader", "sometimes language"],
        campaign_slugs=["apnar-swad-apnar-ghor"],
        expected_signal=(
            "The Assamese campaign's LinkedIn override switches to English, "
            "changes the message to distribution reach, and changes the call "
            "to action to CONTACT DISTRIBUTION — a different reader, not a "
            "different crop."
        ),
        naive_failure="The same headline set at four aspect ratios.",
    ),
    BenchmarkCase(
        case_id="HL-10",
        dimension=LocalisationDimension.CHANNEL,
        question="Does an absent override inherit rather than blank?",
        held_constant=["campaign", "specification"],
        varied=["whether a channel declares an override"],
        campaign_slugs=["apni-raftaar-apna-pause"],
        expected_signal=(
            "Instagram post declares no override and resolves byte-identically "
            "to the campaign default; story and banner differ. Inheritance is "
            "the M11 contract and this case asserts it."
        ),
        naive_failure="An absent override read as an empty headline.",
    ),
    BenchmarkCase(
        case_id="HL-11",
        dimension=LocalisationDimension.ENVIRONMENT,
        question="Is localisation dialled down when it does not help?",
        held_constant=["brand", "product"],
        varied=["audience type (consumer versus trade)"],
        campaign_slugs=["steeped-here", "specified-not-styled"],
        expected_signal=(
            "Both trade campaigns record regional considerations that amount "
            "to 'none' or 'functional only'. Localising a specification sheet "
            "is noise, and the dataset says so rather than localising anyway."
        ),
        naive_failure="Regional cues inserted everywhere because the brand is regional.",
    ),
    BenchmarkCase(
        case_id="HL-12",
        dimension=LocalisationDimension.GOVERNANCE,
        question="Is brand consistency preserved across locations and audiences?",
        held_constant=["brand voice", "palette", "logo rules", "claims"],
        varied=["city", "audience", "language", "channel"],
        campaign_slugs=["veettil-oru-feeling", "onathinu-veedu", "specified-not-styled"],
        expected_signal=(
            "All three Nila campaigns draw their palette from the same four "
            "brand colours and obey the same visual don'ts, while differing "
            "in environment, language and register."
        ),
        naive_failure="Localisation drifting into three different-looking brands.",
    ),
)


class NaiveVsHyperlocal(DomainModel):
    """The explicit product-differentiation comparison.

    Built on Nila Living because Kerala is the case where translation is most
    obviously insufficient: the Malayalam can be perfect and the picture still
    wrong, which is exactly the failure a translation-shaped pipeline cannot
    see.
    """

    campaign_slug: str
    naive_approach: str
    naive_output: list[str]
    naive_failure_modes: list[str]
    campaign_os_approach: str
    campaign_os_output: list[str]
    what_produces_the_difference: list[str]


NAIVE_VS_HYPERLOCAL = NaiveVsHyperlocal(
    campaign_slug="veettil-oru-feeling",
    naive_approach=(
        "Write the campaign in English, translate the strings to Malayalam, "
        "reuse the visual, re-crop per channel."
    ),
    naive_output=[
        "Headline: 'A Feeling At Home' machine-translated to Malayalam",
        "Visual: a warm golden-hour living room, reused from a national shoot",
        "Channels: the same frame cropped to 1:1, 9:16 and 16:9",
        "Claims: whatever the English original said",
    ],
    naive_failure_modes=[
        "Golden-hour light is wrong for Kerala, where the monsoon light that "
        "defines the market is flat, cool and shadowless. The copy is correct "
        "and the picture is from somewhere else.",
        "Translated idiom reads as imported. 'Veettil Oru Feeling' is how the "
        "audience speaks; a translation of 'A Feeling At Home' is not.",
        "Cropping loses the composition's negative space, so type lands on the subject at 9:16.",
        "Claims cross a border without re-checking: 'waterproof' is prohibited "
        "for this brand and a translation pipeline has no opinion about that.",
    ],
    campaign_os_approach=(
        "Conceive in Malayalam from a local audience insight, derive the "
        "environment and light from the market context, hold the brand's "
        "claims and visual rules across every variant, and write per-channel "
        "copy for each channel's reader."
    ),
    campaign_os_output=[
        "Headline: 'മഴ പെയ്യുമ്പോൾ.' — conceived in Malayalam, not translated",
        "Insight: what the audience actually worries about is how the house "
        "feels when it rains and eleven people are in it",
        "Visual: bright flat overcast monsoon light, no hard shadow, "
        "contemporary Kochi apartment, green at the window edge",
        "Refusals recorded: no Kathakali, no houseboats, no coconut-palm "
        "borders, no golden-hour grading",
        "Channels: story carries the headline alone; the web banner switches "
        "to English and names the material, because a specifier reads it",
        "Claims: 'waterproof' and 'mould-proof' forbidden in the specification "
        "itself, so the Guardian checks every variant against them",
    ],
    what_produces_the_difference=[
        "Campaign Specification as source of truth — region, language and "
        "occasion are structured fields, not prose to be translated",
        "Local market context separating credible cues from tokenising ones, "
        "so 'be local' has a direction and a refusal",
        "Reference Intelligence carrying style without reproducible content, "
        "so a mood transfers and a design does not",
        "Per-channel copy as a sparse diff, so a channel adapts where it "
        "needs to and inherits where it does not",
        "Brand Guardian checking every override, not only the default copy",
    ],
)
