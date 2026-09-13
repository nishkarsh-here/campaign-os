"""Creative Context assembly.

Combines the four sources that exist by Milestone 4 into one typed object the
Creative Director will consume in Milestone 5:

    Brand Brain  +  Campaign Specification  +  Reference Style DNA  +  Preferences

Assembled here, once, so no future node re-derives brand rules or re-weights
preferences for itself — that duplication is how brand logic ends up scattered
across a graph.

Everything it reads comes through organization-scoped repositories, so a
context can only ever be built from one organization's resources.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CampaignRow
from app.domain.campaign import CampaignBrief
from app.domain.common import StyleFamily
from app.domain.creative_context import BrandGuardrails, CreativeContext
from app.domain.reference import CreativePreferences, VisualStyleProfile
from app.providers.base import EmbeddingProvider, LLMProvider, ProviderError, StorageProvider
from app.repositories.brands import BrandRepository
from app.repositories.campaigns import CampaignSpecificationRepository
from app.services.brand_knowledge import BrandKnowledgeRetriever
from app.services.brands import row_to_profile
from app.services.reference_intelligence import (
    ReferenceIntelligenceService,
    styles_from_analyses,
)


def build_preferences(
    *,
    selected_styles: list[StyleFamily],
    reference_styles: list[StyleFamily],
    liked: list[str] | None = None,
    disliked: list[str] | None = None,
    color_preference: list[str] | None = None,
    avoid: list[str] | None = None,
    free_text: str | None = None,
) -> CreativePreferences:
    """Turn explicit picks plus observed reference styles into a weighted profile.

    Deterministic by design: the same inputs always give the same weights.
    Preference *learning* is a Level 4 idea and is deliberately not built.
    """
    return CreativePreferences(
        selected_styles=selected_styles,
        liked_reference_ids=liked or [],
        disliked_reference_ids=disliked or [],
        color_preference=color_preference or [],
        avoid=avoid or [],
        free_text=free_text,
        style_profile=VisualStyleProfile.from_sources(
            selected=selected_styles, reference_styles=reference_styles
        ),
    )


class CreativeContextService:
    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        *,
        storage: StorageProvider,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.embeddings = embeddings
        self.brands = BrandRepository(session, organization_id)
        self.specifications = CampaignSpecificationRepository(session, organization_id)
        self.references = ReferenceIntelligenceService(
            session, organization_id, storage=storage, llm=llm
        )

    async def preferences_for(self, campaign: CampaignRow) -> CreativePreferences:
        """Stored picks, re-weighted against the current reference analyses.

        Re-derived rather than stored whole: adding a reference should change
        the profile without the user re-picking anything.
        """
        stored = CreativePreferences.model_validate(campaign.creative_preferences or {})
        analyses = await self.references.analyses_for_campaign(campaign.id)
        return build_preferences(
            selected_styles=stored.selected_styles,
            reference_styles=styles_from_analyses(analyses),
            liked=stored.liked_reference_ids,
            disliked=stored.disliked_reference_ids,
            color_preference=stored.color_preference,
            avoid=stored.avoid,
            free_text=stored.free_text,
        )

    async def build(self, campaign: CampaignRow) -> CreativeContext:
        """Assemble the context for an already-scope-checked campaign row."""
        gaps: list[str] = []

        specification: CampaignBrief | None = None
        latest = await self.specifications.latest(campaign.id)
        if latest is not None:
            specification = CampaignBrief.model_validate(latest.payload)
        else:
            gaps.append("No campaign specification yet — finish discovery first.")

        brand_row = await self.brands.get(campaign.brand_profile_id)
        brand = row_to_profile(brand_row) if brand_row is not None else None
        if brand is None:
            gaps.append("This campaign's brand could not be loaded.")

        analyses = await self.references.analyses_for_campaign(campaign.id)
        reference_style = await self.references.aggregate_for_campaign(campaign.id)
        if not analyses:
            gaps.append("No analysed references — the visual direction is unguided.")

        preferences = await self.preferences_for(campaign)
        if not preferences.selected_styles and not analyses:
            gaps.append("No visual preferences chosen.")

        # Brand knowledge is a bonus, never a blocker: retrieval failing must
        # not prevent a context from being assembled.
        knowledge = None
        if brand_row is not None and specification is not None:
            try:
                retriever = BrandKnowledgeRetriever(
                    self.session, self.organization_id, embeddings=self.embeddings
                )
                knowledge = await retriever.as_brand_knowledge(
                    brand_id=brand_row.id,
                    query=f"{specification.objective} {specification.audience} tone claims",
                    top_k=5,
                )
            except ProviderError:
                gaps.append("Brand knowledge search is unavailable.")

        return CreativeContext(
            campaign_id=str(campaign.id),
            brand_id=str(campaign.brand_profile_id),
            specification=specification,
            brand_name=brand.name if brand else None,
            guardrails=BrandGuardrails.from_brand(brand),
            brand_knowledge=knowledge,
            reference_style=reference_style,
            reference_analyses=analyses,
            preferences=preferences,
            style_profile=preferences.style_profile,
            gaps=gaps,
        )

    async def save_preferences(
        self, campaign: CampaignRow, preferences: CreativePreferences
    ) -> CreativePreferences:
        """Persist the user's picks. Weights are recomputed on read."""
        campaign.creative_preferences = preferences.model_dump(mode="json")
        await self.session.flush()
        return await self.preferences_for(campaign)


def context_payload(context: CreativeContext) -> dict[str, Any]:
    """Serialised form, for an API response or a future graph node."""
    return context.model_dump(mode="json")
