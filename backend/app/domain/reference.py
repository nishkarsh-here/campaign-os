"""Reference Intelligence.

The system learns *style* from an uploaded reference; it never reproduces the
reference. Everything here is a vocabulary of **abstract visual attributes** —
"low-key studio lighting, product dominant, sparse" — from which a later stage
can compose something new.

That is a deliberate IP boundary, not an implementation detail:

* no field stores the reference's own copy, logos, or brand marks;
* no field records exact coordinates, measurements or a layout that could be
  replayed to reconstruct the original;
* typography is described by *character* (weight, case, density), never by
  reconstructed font family — guessing a foundry's typeface from a JPEG is
  both unreliable and the wrong thing to reproduce.

`ReferenceAnalysis.forbids_reproduction()` states the rule in code so a later
milestone cannot quietly widen it.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from app.domain.common import Confidence, DomainModel, Id, JobStatus, StyleFamily, new_id


class ReferenceStatus(StrEnum):
    """Explicit processing states. A provider failure is never COMPLETED."""

    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    def is_terminal(self) -> bool:
        return self in (ReferenceStatus.COMPLETED, ReferenceStatus.FAILED)


class CampaignReference(DomainModel):
    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    storage_key: str
    mime_type: str
    status: JobStatus = JobStatus.PENDING
    error: str | None = None


class Composition(StrEnum):
    CENTERED = "centered"
    ASYMMETRIC = "asymmetric"
    GRID = "grid"
    NEGATIVE_SPACE = "large_negative_space"
    PRODUCT_DOMINANT = "product_dominant"
    PEOPLE_DOMINANT = "people_dominant"
    TYPOGRAPHY_DOMINANT = "typography_dominant"


class Lighting(StrEnum):
    NATURAL = "natural"
    STUDIO = "studio"
    CINEMATIC = "cinematic"
    HIGH_KEY = "high_key"
    LOW_KEY = "low_key"


class ImageryStyle(StrEnum):
    PHOTOREALISTIC = "photorealistic"
    ILLUSTRATIVE = "illustrative"
    ABSTRACT = "abstract"
    PRODUCT_PHOTOGRAPHY = "product_photography"
    LIFESTYLE = "lifestyle"
    ARCHITECTURAL = "architectural"
    HUMAN_CENTRIC = "human_centric"


class VisualDensity(StrEnum):
    SPARSE = "sparse"
    BALANCED = "balanced"
    DENSE = "dense"


class ColorProfile(DomainModel):
    """Colour as measurable qualities, not as a copied swatch set."""

    dominant_palette: list[str] = Field(
        default_factory=list, max_length=8, description="Hex values observed."
    )
    brightness: Confidence = Field(default=0.5, description="0 dark, 1 bright.")
    saturation: Confidence = Field(default=0.5, description="0 muted, 1 vivid.")
    contrast: Confidence = Field(default=0.5, description="0 flat, 1 high contrast.")
    temperature: str | None = Field(default=None, description="warm | neutral | cool")


class TypographyCharacter(DomainModel):
    """How the type *behaves*, never which typeface it is.

    Identifying a font family from an image is unreliable, and reproducing
    someone's typeface is the copying this milestone forbids. Weight, case and
    density are what a later stage actually needs.
    """

    scale: str | None = Field(default=None, description="large | medium | small")
    weight: str | None = Field(default=None, description="light | regular | bold")
    classification: str | None = Field(default=None, description="serif | sans_serif | mixed")
    case: str | None = Field(default=None, description="upper | title | sentence | mixed")
    text_density: VisualDensity | None = None


class LayoutProfile(DomainModel):
    image_text_balance: str | None = Field(
        default=None, description="image_led | balanced | text_led"
    )
    subject_placement: str | None = Field(
        default=None, description="Coarse region: left | centre | right | upper | lower"
    )
    hierarchy: str | None = Field(default=None, description="How attention is ordered, in words.")


class ReferenceAnalysis(DomainModel):
    """Extracted style attributes for one reference.

    Abstract by construction: every field describes a visual *quality*, and
    none of them records content that could reconstruct the original.
    """

    reference_id: Id

    style_families: list[StyleFamily] = Field(default_factory=list, max_length=4)
    composition: Composition | None = None
    lighting: Lighting | None = None
    imagery_style: list[ImageryStyle] = Field(default_factory=list, max_length=4)
    color: ColorProfile = Field(default_factory=ColorProfile)
    typography: TypographyCharacter = Field(default_factory=TypographyCharacter)
    layout: LayoutProfile = Field(default_factory=LayoutProfile)
    visual_density: VisualDensity | None = None
    mood: list[str] = Field(default_factory=list, max_length=6)
    subject_treatment: str | None = None

    #: What we take forward, phrased as guidance rather than description.
    style_takeaways: list[str] = Field(default_factory=list, max_length=6)
    #: Stated plainly for the user: what we did NOT take.
    not_transferable: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Elements belonging to the source that will not be reused.",
    )
    confidence: Confidence = 0.6
    #: Free-text summary for a human reviewing the analysis. Not reasoning.
    summary: str | None = Field(default=None, max_length=600)

    @staticmethod
    def forbids_reproduction() -> tuple[str, ...]:
        """The IP boundary, in code.

        A later milestone adding any of these to the schema would be crossing
        from "learn the style" into "copy the design", so the rule lives here
        rather than only in a document.
        """
        return (
            "verbatim copy or headline text from the reference",
            "logos, wordmarks or brand assets belonging to the reference",
            "exact coordinates, measurements or a replayable layout",
            "identified font families",
            "any instruction to recreate the reference",
        )


class AggregateReferenceStyle(DomainModel):
    """What the references say *together* — the Creative Director reads this,
    not the individual analyses, so three references produce one coherent
    direction rather than three competing ones."""

    dominant_styles: list[StyleFamily] = Field(default_factory=list, max_length=4)
    shared_palette: list[str] = Field(default_factory=list, max_length=8)
    shared_takeaways: list[str] = Field(default_factory=list, max_length=8)
    tensions: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Where references disagree; surfaced to the user rather than averaged away.",
    )
    #: Most common value across the set, where the set agrees.
    common_composition: Composition | None = None
    common_lighting: Lighting | None = None
    common_density: VisualDensity | None = None
    average_color: ColorProfile = Field(default_factory=ColorProfile)
    reference_count: int = 0


class StyleWeight(DomainModel):
    """One style family and how strongly it is wanted."""

    style: StyleFamily
    weight: Confidence


class VisualStyleProfile(DomainModel):
    """A weighted style fingerprint.

    Deterministic, not learned: weights come from explicit user picks and from
    how often a style appears across the analysed references. Preference
    *learning* is a Level 4 idea and deliberately not built here.
    """

    weights: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def from_sources(
        cls,
        *,
        selected: list[StyleFamily],
        reference_styles: list[StyleFamily],
        selected_weight: float = 0.6,
        reference_weight: float = 0.4,
    ) -> VisualStyleProfile:
        """Combine what the user chose with what their references show.

        An explicit pick outweighs an inferred one — the user asking for
        "premium" should not be outvoted by three references that happen to be
        cinematic.
        """
        weights: dict[str, float] = {}
        if selected:
            share = selected_weight / len(selected)
            for style in selected:
                weights[style.value] = weights.get(style.value, 0.0) + share
        if reference_styles:
            share = reference_weight / len(reference_styles)
            for style in reference_styles:
                weights[style.value] = weights.get(style.value, 0.0) + share

        if not weights:
            return cls()
        peak = max(weights.values())
        # Normalise so the strongest signal is 1.0 and the rest are relative.
        return cls(weights={k: round(v / peak, 3) for k, v in sorted(weights.items())})

    def top(self, limit: int = 3) -> list[StyleWeight]:
        ordered = sorted(self.weights.items(), key=lambda kv: (-kv[1], kv[0]))
        return [
            StyleWeight(style=StyleFamily(name), weight=weight)
            for name, weight in ordered[:limit]
            if name in {s.value for s in StyleFamily}
        ]

    def describe(self) -> str:
        """One line a human can read, and a later stage can put in a prompt."""
        parts = [f"{w.style.value.replace('_', ' ')} ({w.weight:.0%})" for w in self.top()]
        return ", ".join(parts) if parts else "no stated visual preference"


class CreativePreferences(DomainModel):
    """Structured visual taste, from the Style Explorer and/or references."""

    selected_styles: list[StyleFamily] = Field(default_factory=list)
    liked_reference_ids: list[Id] = Field(default_factory=list)
    disliked_reference_ids: list[Id] = Field(default_factory=list)
    color_preference: list[str] = Field(default_factory=list, max_length=8)
    avoid: list[str] = Field(default_factory=list, max_length=10)
    free_text: str | None = Field(default=None, max_length=1000)
    #: Derived, not entered. Rebuilt whenever picks or analyses change.
    style_profile: VisualStyleProfile = Field(default_factory=VisualStyleProfile)
