"""Market / localization intelligence.

Regional relevance is a stated product goal ("architects in Maharashtra"), so
region is a first-class input to the creative, not a line appended to a prompt.
This node is degrade-safe: when it fails the brief simply records that context
was unavailable.
"""

from __future__ import annotations

from pydantic import Field

from app.domain.common import Confidence, DomainModel


class MarketContext(DomainModel):
    category_summary: str | None = None
    audience_behaviour: list[str] = Field(default_factory=list)
    competitor_notes: list[str] = Field(default_factory=list)
    current_trends: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list, description="URLs when a SearchProvider ran.")
    confidence: Confidence = 0.5
    available: bool = True


class RegionalContext(DomainModel):
    region: str | None = None
    language: str = "en"
    cultural_notes: list[str] = Field(default_factory=list)
    seasonal_context: str | None = None
    relevant_events: list[str] = Field(
        default_factory=list, description="Festivals/events worth referencing."
    )
    visual_cues: list[str] = Field(
        default_factory=list, description="Regionally credible imagery, e.g. local materials."
    )
    sensitivities: list[str] = Field(
        default_factory=list, description="What to avoid. Checked by the Brand Guardian."
    )
    available: bool = True
