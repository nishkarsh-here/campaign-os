"""The shapes the benchmark adds on top of the domain models.

Everything substantive in this package is an ordinary domain object —
`BrandProfile`, `CampaignBrief`, `CreativeDirection`, `CreativeSpecification`,
`ReferenceAnalysis`. That is deliberate: a benchmark expressed in its own
private schema proves only that the benchmark is self-consistent, whereas one
expressed in the product's real contracts fails to typecheck the moment it
drifts from them.

What lives here is only what the domain has no field for, because it is
metadata *about a test case* rather than campaign truth: which city a company
sits in, how large it is, which languages it operates in, and what the
localisation of a given campaign is actually being tested for.

**Every company, brand, person, product, claim and campaign in this package is
fictional.** They were written for this benchmark. Any resemblance to a real
business is coincidental, and nothing here should be read as market research.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.brand import BrandProfile
from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, DomainModel
from app.domain.creative import CreativeDirection, CreativeSpecification
from app.domain.reference import ReferenceAnalysis


class CompanySize(StrEnum):
    """Governance weight, not headcount.

    The benchmark's interest in company size is entirely about how much
    approval machinery a campaign has to pass through: a startup founder
    signs off their own headline, an enterprise brand team cannot.
    """

    STARTUP = "startup"
    MID_SIZE = "mid_size"
    ENTERPRISE = "enterprise"


class LocalMarketContext(DomainModel):
    """What is true about a place that changes the work.

    Deliberately not "facts about the region". Climate, festivals and
    languages only matter here insofar as they change a campaign, so each
    field is phrased as a constraint on the creative rather than trivia.
    """

    city: str
    state: str
    #: Why this location changes the campaign, in one sentence.
    localisation_thesis: str
    #: Environmental and material cues a local audience would find credible.
    credible_cues: list[str] = Field(default_factory=list, max_length=12)
    #: Cues that would read as tourism-brochure shorthand to a local.
    #: The most important field in this model: the benchmark is largely a
    #: test of whether the system can localise *without* reaching for these.
    tokenising_cues: list[str] = Field(default_factory=list, max_length=12)
    #: Seasonal or occasion pressure that shifts what a campaign can say.
    seasonal_notes: list[str] = Field(default_factory=list, max_length=8)


class LanguagePreference(DomainModel):
    """How a language is actually used, which is rarely "translate it"."""

    language: str
    #: Where this language leads and where it supports.
    usage: str
    #: Script expectations — transliteration is a real choice, not a fallback.
    script: str
    #: Copy that must never be machine-translated: claims, legal, product names.
    never_translate: list[str] = Field(default_factory=list, max_length=10)


class BenchmarkCampaign(DomainModel):
    """One campaign, complete enough to walk the real pipeline."""

    slug: str
    #: The approved Campaign Specification — the source of truth (ADR: §3.1).
    brief: CampaignBrief
    #: Three genuinely different strategic answers to the same brief.
    directions: list[CreativeDirection] = Field(min_length=3, max_length=3)
    #: The execution plan compiled from the chosen direction, including the
    #: per-channel copy overrides that make this campaign one plan expressed
    #: differently rather than one plan resized (M11).
    specification: CreativeSpecification
    #: Which direction the (simulated) human chose at Gate 1.
    selected_direction_ordinal: int = 1
    #: What this campaign is in the benchmark to prove.
    tests: list[str] = Field(default_factory=list, max_length=8)


class BenchmarkCompany(DomainModel):
    """A fictional company, its brand governance, and its campaigns."""

    slug: str
    display_name: str
    size: CompanySize
    industry: str
    market: LocalMarketContext
    languages: list[LanguagePreference] = Field(min_length=1, max_length=4)
    #: The Brand Brain: confirmed facts only, exactly as the product requires.
    brand: BrandProfile
    #: Abstract style references. No reproducible content anywhere in them,
    #: because `ReferenceAnalysis` has nowhere to put any (ADR-011).
    references: list[ReferenceAnalysis] = Field(default_factory=list, max_length=8)
    campaigns: list[BenchmarkCampaign] = Field(min_length=1, max_length=5)
    #: Why this company earns a place in the benchmark.
    selection_rationale: str = ""

    @property
    def organization_slug(self) -> str:
        """The tenant this company's data lives in.

        One organization per company, never a shared one with a filter: the
        benchmark's first claim is tenant isolation, and a shared tenant
        could only ever demonstrate that a `WHERE` clause was remembered.
        """
        return f"benchmark-{self.slug}"


#: The channels every benchmark campaign carries copy for.
#:
#: Both Instagram feed formats are here on purpose. A real brand runs the
#: square and the 4:5 portrait side by side, and they are not the same frame:
#: the portrait is the tallest the feed will show uncropped, so it carries a
#: different safe area and a different type scale. The dataset's first draft
#: had to fake 4:5 with the square because the channel did not exist; it now
#: does, and the campaigns that are feed-led target it.
BENCHMARK_CHANNELS: tuple[Channel, ...] = (
    Channel.INSTAGRAM_POST,
    Channel.INSTAGRAM_PORTRAIT,
    Channel.INSTAGRAM_STORY,
    Channel.LINKEDIN,
    Channel.WEB_BANNER,
)

#: Stamped on every fictional entity this package creates.
FICTIONAL_NOTICE = (
    "Fictional company created for the Campaign OS hyperlocal benchmark. "
    "Not a real business; claims and figures are synthetic."
)
