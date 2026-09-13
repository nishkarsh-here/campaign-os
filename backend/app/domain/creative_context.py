"""Creative Context.

One assembled answer to "what should this campaign look and feel like?",
combining the four sources that exist by Milestone 4:

    Brand Brain  +  Campaign Specification  +  Reference Style DNA  +  Preferences

It exists so the Creative Director (Milestone 5) consumes a single typed object
instead of re-deriving brand rules, re-reading references and re-weighting
preferences itself. Getting that wrong is how brand logic ends up copied into
every future node.

It is composed, never stored as a separate source of truth: rebuild it and you
get the same answer, because every part of it is owned elsewhere.
"""

from __future__ import annotations

from pydantic import Field

from app.domain.brand import BrandKnowledge, BrandProfile
from app.domain.campaign import CampaignBrief
from app.domain.common import DomainModel, Id, StyleFamily
from app.domain.reference import (
    AggregateReferenceStyle,
    CreativePreferences,
    ReferenceAnalysis,
    VisualStyleProfile,
)


class BrandGuardrails(DomainModel):
    """The brand's non-negotiables, lifted out so a later stage cannot miss them.

    A flattened copy on purpose: the Creative Director should not have to walk
    a `BrandProfile` to discover what it must not say.
    """

    palette: list[str] = Field(default_factory=list, max_length=8)
    tone_attributes: list[str] = Field(default_factory=list, max_length=8)
    approved_claims: list[str] = Field(default_factory=list, max_length=20)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=20)
    visual_dos: list[str] = Field(default_factory=list, max_length=15)
    visual_donts: list[str] = Field(default_factory=list, max_length=15)
    logo_rules: list[str] = Field(default_factory=list, max_length=10)
    legal_line: str | None = None

    @classmethod
    def from_brand(cls, brand: BrandProfile | None) -> BrandGuardrails:
        if brand is None:
            return cls()
        return cls(
            palette=[c.hex for c in brand.colors],
            tone_attributes=list(brand.voice.tone_attributes),
            approved_claims=list(brand.approved_claims),
            prohibited_claims=list(brand.prohibited_claims),
            visual_dos=list(brand.visual_dos),
            visual_donts=list(brand.visual_donts),
            logo_rules=list(brand.logo_rules),
            legal_line=brand.legal_line,
        )


class CreativeContext(DomainModel):
    """Everything a creative decision needs, assembled once."""

    campaign_id: Id
    brand_id: Id | None = None

    # --- what the campaign is trying to do -----------------------------
    specification: CampaignBrief | None = None

    # --- who the brand is ----------------------------------------------
    brand_name: str | None = None
    guardrails: BrandGuardrails = Field(default_factory=BrandGuardrails)
    brand_knowledge: BrandKnowledge | None = None

    # --- what it should look like ---------------------------------------
    reference_style: AggregateReferenceStyle = Field(default_factory=AggregateReferenceStyle)
    reference_analyses: list[ReferenceAnalysis] = Field(default_factory=list, max_length=20)
    preferences: CreativePreferences = Field(default_factory=CreativePreferences)
    style_profile: VisualStyleProfile = Field(default_factory=VisualStyleProfile)

    # --- honesty about what is missing -----------------------------------
    #: Named gaps, so a later stage proceeds knowingly rather than filling
    #: them in silently.
    gaps: list[str] = Field(default_factory=list, max_length=10)

    def is_ready(self) -> bool:
        """Enough to brief a creative decision.

        A confirmed specification is the floor. References and preferences
        sharpen the direction but a campaign can proceed on brand alone.
        """
        return self.specification is not None

    def dominant_styles(self, limit: int = 3) -> list[StyleFamily]:
        return [w.style for w in self.style_profile.top(limit)]

    def summarise(self) -> str:
        """A short, user-facing account of the creative direction.

        Deliberately a summary, not reasoning (CLAUDE.md rule 8).
        """
        lines: list[str] = []
        if self.specification is not None:
            lines.append(f"{self.specification.objective} for {self.specification.audience}.")
        if self.brand_name:
            tone = ", ".join(self.guardrails.tone_attributes[:3])
            lines.append(f"{self.brand_name}{f' — {tone}' if tone else ''}.")
        style = self.style_profile.describe()
        if style != "no stated visual preference":
            lines.append(f"Visual direction: {style}.")
        if self.reference_style.reference_count:
            lines.append(f"Drawn from {self.reference_style.reference_count} reference(s).")
        if self.guardrails.prohibited_claims:
            lines.append(f"Must avoid: {', '.join(self.guardrails.prohibited_claims[:3])}.")
        return " ".join(lines) or "Not enough information yet."
