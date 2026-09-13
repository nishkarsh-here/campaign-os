"""Retrieval and Brand Brain composition.

`BrandKnowledgeRetriever` is deliberately small and free of campaign concepts.
Milestone 3+ campaign nodes will ask it "what does this brand say about X?" and
get passages with scores and sources — so brand logic lives here once, not
copied into every future node.

`BrandBrainService` composes the whole picture: confirmed profile, retrievable
knowledge, source documents, assets, and the AI proposals still awaiting a
human. That composition is what a campaign node means by "give me the brand
context for this campaign".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandAssetRow, BrandDocumentRow, BrandFactRow, BrandProfileRow
from app.domain.brand import (
    BrandFieldStatus,
    BrandKnowledge,
    BrandKnowledgeChunk,
    BrandProfile,
    FieldKnowledge,
)
from app.providers.base import EmbeddingProvider
from app.repositories.brands import (
    BrandAssetRepository,
    BrandChunkRepository,
    BrandDocumentRepository,
    BrandFactRepository,
)
from app.services.brands import row_to_profile

#: The fields the Brand Brain reports known/unknown/inferred coverage for.
#: Chosen because these are what downstream creative work actually consumes.
TRACKED_FIELDS: tuple[str, ...] = (
    "positioning",
    "audience_description",
    "voice.tone_attributes",
    "values",
    "colors",
    "typography",
    "approved_claims",
    "prohibited_claims",
    "visual_dos",
    "visual_donts",
    "logo_rules",
    "products",
)


@dataclass(frozen=True)
class ComposedBrandBrain:
    """The assembled Brand Brain.

    A typed result rather than a dict: this is domain data, and the router maps
    it field by field (CLAUDE.md rule 3).
    """

    profile: BrandProfile
    documents: list[BrandDocumentRow]
    assets: list[BrandAssetRow]
    proposed_facts: list[BrandFactRow]
    field_status: list[BrandFieldStatus]
    chunk_count: int
    knowledge_ready: bool
    processing_errors: list[str]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    chunk_index: int
    page: int | None


class BrandKnowledgeRetriever:
    """Semantic search over one brand's knowledge.

    Scoping is not optional and not a parameter a caller can forget: the
    organization comes from construction and the brand from every call, and
    `BrandChunkRepository.search` applies both.
    """

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        *,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.embeddings = embeddings
        self.chunks = BrandChunkRepository(session, organization_id)
        self.documents = BrandDocumentRepository(session, organization_id)

    async def retrieve(
        self, *, brand_id: uuid.UUID, query: str, top_k: int = 5
    ) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        vector = (await self.embeddings.embed([query]))[0]
        hits = await self.chunks.search(brand_id=brand_id, embedding=vector, top_k=top_k)
        if not hits:
            return []

        # One lookup for the titles rather than one per hit.
        titles = {doc.id: doc.title for doc in await self.documents.list_for_brand(brand_id)}
        return [
            RetrievedChunk(
                chunk_id=str(row.id),
                document_id=str(row.brand_document_id),
                document_title=titles.get(row.brand_document_id, "Untitled document"),
                content=row.content,
                score=round(score, 4),
                chunk_index=row.chunk_index,
                page=row.page,
            )
            for row, score in hits
        ]

    async def as_brand_knowledge(
        self, *, brand_id: uuid.UUID, query: str, top_k: int = 5
    ) -> BrandKnowledge:
        """The domain shape campaign nodes will read from `CampaignState`.

        Returning the existing `BrandKnowledge` type — rather than inventing a
        second one — is what lets Milestone 4 consume this without adaptation.
        """
        return BrandKnowledge(
            query=query,
            chunks=[
                BrandKnowledgeChunk(
                    id=hit.chunk_id,
                    document_id=hit.document_id,
                    document_title=hit.document_title,
                    content=hit.content,
                    score=hit.score,
                    chunk_index=hit.chunk_index,
                    page=hit.page,
                )
                for hit in await self.retrieve(brand_id=brand_id, query=query, top_k=top_k)
            ],
        )


def _field_value(profile: BrandProfile, path: str) -> object:
    current: object = profile
    for part in path.split("."):
        current = getattr(current, part, None)
        if current is None:
            return None
    return current


def _has_content(value: object) -> bool:
    """Is this field actually populated?

    A nested model like `BrandTypography()` is truthy even when every field in
    it is empty, so a plain `bool()` reports an untouched brand as "known".
    Unwrap one level and ask whether anything inside carries content.
    """
    if value is None:
        return False
    if isinstance(value, BaseModel):
        return any(_has_content(v) for v in value.model_dump().values())
    if isinstance(value, bool):
        return True
    if isinstance(value, str | list | tuple | set | dict):
        return len(value) > 0
    return True


def field_status(profile: BrandProfile, proposed_fields: set[str]) -> list[BrandFieldStatus]:
    """known / unknown / inferred, per tracked field.

    A field is KNOWN only when it is set on the confirmed profile. A proposal
    alone makes it INFERRED — never KNOWN — which is the whole point: an AI
    guess must not read as an established brand fact.
    """
    out: list[BrandFieldStatus] = []
    for path in TRACKED_FIELDS:
        has_value = _has_content(_field_value(profile, path))
        proposals = sum(1 for f in proposed_fields if f == path)
        if has_value:
            knowledge = FieldKnowledge.KNOWN
        elif proposals:
            knowledge = FieldKnowledge.INFERRED
        else:
            knowledge = FieldKnowledge.UNKNOWN
        out.append(BrandFieldStatus(field=path, knowledge=knowledge, proposal_count=proposals))
    return out


class BrandBrainService:
    """One call, everything a consumer needs to know about a brand."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        *,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.documents = BrandDocumentRepository(session, organization_id)
        self.assets = BrandAssetRepository(session, organization_id)
        self.facts = BrandFactRepository(session, organization_id)
        self.chunks = BrandChunkRepository(session, organization_id)
        self.retriever = BrandKnowledgeRetriever(session, organization_id, embeddings=embeddings)

    async def compose(self, brand_row: BrandProfileRow) -> ComposedBrandBrain:
        """Assemble the Brand Brain view for an already-scope-checked brand row."""
        profile = row_to_profile(brand_row)
        brand_id = uuid.UUID(profile.id)

        documents = await self.documents.list_for_brand(brand_id)
        assets = await self.assets.list_for_brand(brand_id)
        proposed = await self.facts.list_for_brand(brand_id, status="proposed")
        chunk_count = await self.chunks.count_for_brand(brand_id)

        return ComposedBrandBrain(
            profile=profile,
            documents=documents,
            assets=assets,
            proposed_facts=proposed,
            field_status=field_status(profile, {f.field for f in proposed}),
            chunk_count=chunk_count,
            knowledge_ready=chunk_count > 0,
            # Surfaced so the page can say which document failed and why,
            # instead of showing an unexplained gap.
            processing_errors=[f"{doc.title}: {doc.error}" for doc in documents if doc.error],
        )
