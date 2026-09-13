"""Creative Direction and Creative Specification.

These are the two most important schemas in the system.

A `CreativeDirection` is a *strategic option* a human chooses between. Three of
them, meaningfully different, each with a rationale.

A `CreativeSpecification` is the approved direction resolved into a complete,
unambiguous creative plan. It is the single source of truth for generation
(ARCHITECTURE §3): prompts are compiled from it and are disposable, it is not.
"""

from __future__ import annotations

import re

from pydantic import Field, model_validator

from app.domain.common import DomainModel, Id, StyleFamily, new_id

#: Words that carry no distinguishing signal when comparing two directions.
_STOPWORDS = frozenset(
    {
        "with",
        "that",
        "this",
        "from",
        "into",
        "over",
        "under",
        "your",
        "their",
        "which",
        "while",
        "where",
        "there",
        "here",
        "have",
        "been",
        "were",
        "they",
        "them",
        "then",
        "than",
        "some",
        "more",
        "most",
        "very",
        "much",
        "such",
        "shot",
        "image",
        "scene",
        "frame",
        "feel",
        "feels",
        "sense",
        "looks",
    }
)


class TypographyGuidance(DomainModel):
    headline_treatment: str | None = None
    hierarchy: str | None = None
    max_headline_chars: int = Field(default=60, ge=10, le=200)


class NegativeConstraints(DomainModel):
    """What must not appear. Fed to the image model as negatives *and* checked
    by the Brand Guardian after generation — belt and braces, because image
    models treat negatives as suggestions."""

    forbidden_elements: list[str] = Field(default_factory=list)
    forbidden_text: list[str] = Field(default_factory=list)
    avoid_styles: list[str] = Field(default_factory=list)
    no_text_in_image: bool = Field(
        default=True,
        description=(
            "Default True: text is composed deterministically afterwards (ADR-006). "
            "Generated lettering is unreliable and off-brand."
        ),
    )


class CreativeDirection(DomainModel):
    """One strategic option. Distinct from its siblings in *idea*, not in detail."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    ordinal: int = Field(ge=1, le=5)

    title: str = Field(description="Short handle, e.g. 'Built to Outlast'.")
    big_idea: str = Field(description="The concept in one line.")
    strategic_rationale: str = Field(description="Why this works for this brief. User-facing.")
    emotional_angle: str
    #: How this angle connects to the specific audience in the specification.
    audience_connection: str = ""
    key_message: str = ""

    headline: str
    subhead: str | None = None
    cta: str
    cta_direction: str = Field(default="", description="How the CTA should feel and where it sits.")

    visual_metaphor: str
    composition: str
    subject: str
    environment: str
    lighting: str
    palette: list[str] = Field(default_factory=list)
    style_families: list[StyleFamily] = Field(default_factory=list)

    color_direction: str = Field(default="", description="The palette's intent, in words.")

    brand_integration: str = Field(description="How the brand shows up beyond the logo.")
    product_integration: str
    #: Only what the campaign context already establishes. Inventing regional
    #: facts the context does not contain is worse than saying nothing.
    regional_considerations: list[str] = Field(default_factory=list, max_length=6)
    negative_constraints: NegativeConstraints = Field(default_factory=NegativeConstraints)

    #: Which reference *characteristics* this direction deliberately carries
    #: forward — abstract qualities only (ADR-011), never reference content.
    reference_characteristics_used: list[str] = Field(default_factory=list, max_length=6)
    #: And which it deliberately leaves behind. Stating both makes the IP
    #: boundary visible in the product rather than only in the schema.
    reference_characteristics_avoided: list[str] = Field(default_factory=list, max_length=6)

    #: Used by the distinctness check that stops three directions being one idea.
    distinctness_note: str | None = None

    def diversity_signature(self) -> frozenset[str]:
        """The structured features distinctness is measured on.

        Deliberately not the prose: two directions can be worded differently
        and still be the same idea. Comparing the *choices* — angle, subject,
        setting, framing, light — is what catches "the same poster with a
        different background".
        """
        words = " ".join(
            (
                self.emotional_angle,
                self.subject,
                self.environment,
                self.composition,
                self.lighting,
                self.visual_metaphor,
            )
        ).lower()
        tokens = {w for w in re.findall(r"[a-z]{4,}", words) if w not in _STOPWORDS}
        return frozenset(tokens | {f"style:{s.value}" for s in self.style_families})


class CreativeSpecification(DomainModel):
    """The approved creative plan. Everything generation needs, nothing it doesn't."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    direction_id: Id
    version: int = 1

    concept: str
    #: The scene in a sentence or two: what is happening and why it reads.
    visual_story: str = ""
    emotional_angle: str
    headline: str
    headline_guidance: str = Field(default="", description="How the headline should be set.")
    subhead: str | None = None
    cta: str
    cta_guidance: str = ""
    body_copy: str | None = None

    visual_metaphor: str
    composition: str
    focal_point: str = Field(default="", description="What the eye lands on first.")
    subject: str
    environment: str
    lighting: str
    camera: str | None = Field(default=None, description="e.g. '35mm, eye level, shallow depth'")
    palette: list[str] = Field(default_factory=list)
    color_direction: str = ""
    style_families: list[StyleFamily] = Field(default_factory=list)
    mood: list[str] = Field(default_factory=list)

    typography_guidance: TypographyGuidance = Field(default_factory=TypographyGuidance)
    product_integration: str
    #: Whether people appear, and how they are treated. Explicit because
    #: "add a person" and "no people" are very different creatives.
    people_guidance: str = ""
    brand_integration: str
    regional_cues: list[str] = Field(default_factory=list, max_length=6)
    negative_constraints: NegativeConstraints = Field(default_factory=NegativeConstraints)

    #: Field -> whether a human edited it. A regeneration must not undo an
    #: edit, the same promise the Campaign Specification makes.
    human_edited_fields: list[str] = Field(default_factory=list)

    #: Fields a revision must not touch unless the user explicitly says so.
    #: The revision planner reads this to build its KEEP list (PRODUCT_SPEC §8).
    locked_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _core_present(self) -> CreativeSpecification:
        for field in ("concept", "headline", "cta", "subject", "composition"):
            if not getattr(self, field, None):
                raise ValueError(f"CreativeSpecification.{field} is required")
        return self


class DiversityVerdict(DomainModel):
    """Whether a set of directions is genuinely three ideas or one idea thrice.

    Deterministic set overlap on the structured features, not clustering: the
    question "are these the same poster with a different background?" does not
    need a model, and a model would make the answer unrepeatable.
    """

    passed: bool
    #: (ordinal_a, ordinal_b, similarity) for every pair that is too close.
    collisions: list[tuple[int, int, float]] = Field(default_factory=list)
    #: Lowest pairwise distinctness in the set, for display.
    weakest_pair_similarity: float = 0.0

    def describe(self) -> str:
        if self.passed:
            return "The three directions are meaningfully different."
        pairs = ", ".join(f"{a} and {b}" for a, b, _ in self.collisions)
        return f"Directions {pairs} are too similar to be separate choices."


class CreativeDirectionSet(DomainModel):
    """The three options a human chooses between, plus why one is recommended."""

    campaign_id: Id
    version: int = 1
    directions: list[CreativeDirection] = Field(min_length=1, max_length=5)
    recommended_ordinal: int | None = Field(default=None, ge=1, le=5)
    #: Short, user-facing reasons. Never reasoning traces (CLAUDE.md rule 8).
    recommendation_reasons: list[str] = Field(default_factory=list, max_length=6)
    diversity: DiversityVerdict | None = None
    #: Set when generation happened in response to feedback.
    revision_of_version: int | None = None

    def by_ordinal(self, ordinal: int) -> CreativeDirection | None:
        return next((d for d in self.directions if d.ordinal == ordinal), None)

    def by_id(self, direction_id: str) -> CreativeDirection | None:
        return next((d for d in self.directions if d.id == direction_id), None)


class CreativeRevisionDelta(DomainModel):
    """What a round of feedback changes, and what it must not.

    The KEEP list is the point: "make it more aspirational" must not quietly
    change the product, the audience or a factual claim.
    """

    iteration: int = Field(ge=1)
    feedback: str
    #: What we understood, shown back before anything regenerates.
    interpretation: str = ""
    keep: list[str] = Field(default_factory=list, max_length=20)
    change: list[str] = Field(default_factory=list, max_length=20)
    target_ordinal: int | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def _no_field_both_kept_and_changed(self) -> CreativeRevisionDelta:
        overlap = set(self.keep) & set(self.change)
        if overlap:
            raise ValueError(f"Fields cannot be both kept and changed: {sorted(overlap)}")
        return self


#: Campaign facts a creative revision may never alter. Feedback about tone or
#: imagery has no business changing what the product is or who it is for.
PROTECTED_CAMPAIGN_FACTS: tuple[str, ...] = (
    "product",
    "objective",
    "audience",
    "key_message",
    "cta",
    "channels",
    "region",
)


class CreativeApprovalRecord(DomainModel):
    """A human decision on a direction or a specification. The audit trail."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    gate: str = Field(description="strategy | specification")
    decision: str
    target_id: Id | None = None
    feedback: str | None = None
    decided_by: Id | None = None
