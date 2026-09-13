"""Brand Brain — the persistent brand knowledge every node reads from.

A `BrandProfile` is authored by humans during onboarding and enriched from
ingested documents. `BrandKnowledge` is what RAG retrieval returns for a
specific question. The two are separate because one is stable identity and the
other is a per-query slice.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

from app.domain.common import Confidence, DomainModel, Id, StyleFamily, new_id

HEX = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"


class BrandColor(DomainModel):
    name: str
    hex: str = Field(pattern=HEX)
    role: str = Field(
        default="accent",
        description="primary | secondary | accent | background | text",
    )


class BrandTypography(DomainModel):
    heading_font: str | None = None
    body_font: str | None = None
    fallback_stack: list[str] = Field(default_factory=list)
    notes: str | None = None


class BrandVoice(DomainModel):
    tone_attributes: list[str] = Field(default_factory=list, max_length=8)
    person: str | None = Field(default=None, description="e.g. 'first person plural'")
    writing_rules: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class BrandProduct(DomainModel):
    name: str
    category: str | None = None
    description: str | None = None
    key_features: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)


class BrandAsset(DomainModel):
    """A binary the layout engine can place. `storage_key` is opaque; only the
    StorageProvider resolves it (never a raw filesystem path in state)."""

    id: Id
    kind: str = Field(description="logo | logo_mono | product | font | pattern | other")
    storage_key: str
    mime_type: str
    width: int | None = None
    height: int | None = None


class BrandProfile(DomainModel):
    """**Confirmed** brand facts — the stable identity every node reads.

    Everything here is authoritative: a human typed it, or a human accepted a
    proposal. Model output never lands in this object directly. AI findings are
    `ExtractedFact`s that stay `PROPOSED` until someone accepts them, which is
    what keeps a plausible guess from quietly becoming a brand rule the Brand
    Guardian later enforces.
    """

    id: Id
    organization_id: Id
    name: str
    industry: str | None = None
    description: str | None = None
    website: str | None = None
    positioning: str | None = None
    mission: str | None = None
    values: list[str] = Field(default_factory=list)
    audience_description: str | None = None

    voice: BrandVoice = Field(default_factory=BrandVoice)
    colors: list[BrandColor] = Field(default_factory=list)
    typography: BrandTypography = Field(default_factory=BrandTypography)
    preferred_styles: list[StyleFamily] = Field(default_factory=list)

    products: list[BrandProduct] = Field(default_factory=list)

    # Governance. The Brand Guardian checks against exactly these.
    approved_claims: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    visual_dos: list[str] = Field(default_factory=list)
    visual_donts: list[str] = Field(default_factory=list)
    logo_rules: list[str] = Field(default_factory=list)
    legal_line: str | None = None

    @field_validator("prohibited_claims", "approved_claims")
    @classmethod
    def _no_blanks(cls, v: list[str]) -> list[str]:
        return [s for s in v if s.strip()]

    def primary_color(self) -> BrandColor | None:
        return next((c for c in self.colors if c.role == "primary"), None)


class ProvenanceKind(StrEnum):
    """Where a piece of brand knowledge came from."""

    HUMAN = "human"  # typed into the onboarding form — authoritative
    DOCUMENT = "document"  # quoted from an uploaded document
    INFERRED = "inferred"  # the model's reading, stated nowhere explicitly


class Provenance(DomainModel):
    """The smallest useful provenance record.

    Enough for a future campaign node — or a brand manager — to answer "where
    did this come from?" without building a citation framework.
    """

    kind: ProvenanceKind
    document_id: Id | None = None
    document_title: str | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, max_length=600, description="The supporting text.")


class FactStatus(StrEnum):
    PROPOSED = "proposed"  # the model said it; nobody has agreed yet
    ACCEPTED = "accepted"  # a human confirmed it; safe to merge into the profile
    REJECTED = "rejected"  # a human said no; kept so it is not proposed again


class ExtractedFact(DomainModel):
    """One candidate brand fact produced by extraction.

    Deliberately *not* a `BrandProfile` field. Keeping proposals in their own
    type is what enforces "no AI guess becomes a confirmed brand fact": merging
    is an explicit, auditable act.
    """

    id: Id = Field(default_factory=new_id)
    field: str = Field(description="Dotted path on BrandProfile, e.g. 'voice.tone_attributes'.")
    value: str = Field(min_length=1, max_length=2000)
    confidence: Confidence = 0.5
    provenance: Provenance
    status: FactStatus = FactStatus.PROPOSED
    rationale: str | None = Field(default=None, description="One line, user-facing.")


class BrandExtraction(DomainModel):
    """The LLM's structured output. Validated strictly; never trusted blindly."""

    summary: str = Field(description="What the model understood about the brand, for a human.")
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=200)
    #: What the sources did not say. Honest gaps beat invented ones, and this
    #: drives the "what we still need" prompt in the UI.
    unknown_fields: list[str] = Field(default_factory=list)


class FieldKnowledge(StrEnum):
    KNOWN = "known"  # confirmed on the profile
    INFERRED = "inferred"  # only a proposal exists
    UNKNOWN = "unknown"  # neither


class BrandFieldStatus(DomainModel):
    """Per-field answer to known / unknown / inferred, for the Brand Brain UI."""

    field: str
    knowledge: FieldKnowledge
    proposal_count: int = 0


class DocumentStatus(StrEnum):
    """Explicit per-stage states.

    A failure names the stage it failed at, so the UI can say what to retry
    instead of showing an unexplained spinner. `COMPLETED` is only ever written
    by the stage that genuinely finished.
    """

    PENDING = "PENDING"
    EXTRACTING = "EXTRACTING"
    EMBEDDING = "EMBEDDING"
    COMPLETED = "COMPLETED"
    UPLOAD_FAILED = "UPLOAD_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"

    def is_terminal(self) -> bool:
        return self in {
            DocumentStatus.COMPLETED,
            DocumentStatus.UPLOAD_FAILED,
            DocumentStatus.EXTRACTION_FAILED,
            DocumentStatus.EMBEDDING_FAILED,
            DocumentStatus.ANALYSIS_FAILED,
        }

    def is_failure(self) -> bool:
        return self.name.endswith("FAILED")


class BrandDocument(DomainModel):
    """A source ingested into the Brand Brain."""

    id: Id
    brand_id: Id
    title: str
    source_type: str = Field(description="pdf | text")
    filename: str | None = None
    mime_type: str | None = None
    bytes: int | None = None
    storage_key: str | None = None
    status: DocumentStatus = DocumentStatus.PENDING
    chunk_count: int = 0
    page_count: int | None = None
    #: User-safe. Provider exceptions never reach this field.
    error: str | None = None
    uploaded_at: datetime | None = None


class BrandKnowledgeChunk(DomainModel):
    """One retrieved passage. `score` lets the UI show why the AI said something."""

    id: Id | None = None
    document_id: Id
    document_title: str
    content: str
    score: Confidence
    chunk_index: int = 0
    page: int | None = None


class BrandKnowledge(DomainModel):
    """The retrieval result placed into state for a given campaign."""

    query: str
    chunks: list[BrandKnowledgeChunk] = Field(default_factory=list)

    def as_context(self, max_chars: int = 4000) -> str:
        out: list[str] = []
        used = 0
        for c in self.chunks:
            block = f"[{c.document_title}] {c.content}"
            if used + len(block) > max_chars:
                break
            out.append(block)
            used += len(block)
        return "\n\n".join(out)
