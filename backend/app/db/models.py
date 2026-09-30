"""Migration 001 tables: the tenancy spine.

Only what Milestone 1 needs. Brands, campaigns and everything downstream land
in their own migrations when the workflow that uses them is built — no
speculative columns (CLAUDE.md, DATABASE_SCHEMA §Change policy).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, Timestamps, TimestampsWithUpdate
from app.domain.common import CampaignRecordStatus

ROLES = ("admin", "brand_manager", "marketing", "designer", "viewer")

#: Pinned by migration 002. Changing it needs a migration *and* a re-embed, so
#: `EmbeddingProvider.dimensions` is asserted against it at startup rather than
#: discovered as silent retrieval garbage (ROADMAP risk R-4).
EMBEDDING_DIMENSIONS = 1536

CAMPAIGN_STATUSES = (
    "DRAFT",
    "INTERVIEWING",
    "SPECIFICATION_READY",
    "SPECIFICATION_CONFIRMED",
    "FAILED",
    "CANCELLED",
)

RUN_STATUSES = ("PENDING", "RUNNING", "WAITING_HUMAN", "COMPLETED", "FAILED", "CANCELLED")

DOCUMENT_STATUSES = (
    "PENDING",
    "EXTRACTING",
    "EMBEDDING",
    "COMPLETED",
    "UPLOAD_FAILED",
    "EXTRACTION_FAILED",
    "EMBEDDING_FAILED",
    "ANALYSIS_FAILED",
)
ASSET_KINDS = ("logo", "logo_mono", "product", "font", "pattern", "other")

REFERENCE_STATUSES = ("PENDING", "ANALYZING", "COMPLETED", "FAILED")


class Organization(TimestampsWithUpdate, Entity):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Timestamps, Entity):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    #: The external identity-provider subject. Null for dev-stub users; set
    #: once real auth is wired, which is the only change that adapter needs.
    auth_subject: Mapped[str | None] = mapped_column(Text, unique=True)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Membership(Timestamps, Entity):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        # `GET /me` — which every screen calls — lists a user's memberships by
        # `user_id` alone. The unique constraint above indexes
        # `(organization_id, user_id)`, whose leading column is the wrong one, so
        # that query scanned the table (audit finding PERF-2). Resolving the
        # request principal filters on both columns and could already use it.
        Index("ix_memberships_user_id", "user_id"),
        CheckConstraint(
            "role in ('admin','brand_manager','marketing','designer','viewer')",
            name="role_valid",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Project(TimestampsWithUpdate, Entity):
    __tablename__ = "projects"
    __table_args__ = (
        Index(
            "ix_projects_organization_id_live",
            "organization_id",
            postgresql_where="deleted_at is null",
        ),
        # Keyset pagination order (API_SPEC §Lists). Declared so the ORM and
        # the migrated database describe the same schema.
        Index(
            "ix_projects_organization_id_created_at_id",
            "organization_id",
            "created_at",
            "id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Soft delete: projects are user-recoverable, so rows are retained
    #: (DATABASE_SCHEMA §Conventions). Explicitly timezone-aware — a bare
    #: mapped_column() infers naive DateTime and silently disagrees with the
    #: timestamptz the migration created.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Milestone 2 — Brand Brain
#
# Cardinality decision (ARCHITECTURE_REVIEW M-6, which left it open): a brand
# belongs to an **organization**, not to a project. An agency organization can
# hold several brands, and a project selects one. `project_id` is therefore NOT
# created here — adding it later is an additive migration, whereas a nullable
# column nothing reads is exactly the speculative schema the roadmap forbids.
# ---------------------------------------------------------------------------
class BrandProfileRow(TimestampsWithUpdate, Entity):
    __tablename__ = "brand_profiles"
    __table_args__ = (
        # One brand name per organization: two "Acme" brands in one workspace
        # is a mistake, not a use case.
        UniqueConstraint("organization_id", "name"),
        Index("ix_brand_profiles_organization_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: The validated `domain.brand.BrandProfile`. JSONB with a promoted `name`
    #: for listing, per DATABASE_SCHEMA "The JSONB decision".
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BrandDocumentRow(Timestamps, Entity):
    __tablename__ = "brand_documents"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING','EXTRACTING','EMBEDDING','COMPLETED',"
            "'UPLOAD_FAILED','EXTRACTION_FAILED','EMBEDDING_FAILED','ANALYSIS_FAILED')",
            name="status_valid",
        ),
        CheckConstraint("source_type in ('pdf','text')", name="source_type_valid"),
        Index("ix_brand_documents_brand_profile_id", "brand_profile_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Sanitised. A raw provider exception must never reach this column.
    error: Mapped[str | None] = mapped_column(Text)
    #: Lets re-ingest skip an unchanged file instead of re-embedding it.
    content_sha256: Mapped[str | None] = mapped_column(String(64))


class BrandAssetRow(Timestamps, Entity):
    __tablename__ = "brand_assets"
    __table_args__ = (
        CheckConstraint(
            "kind in ('logo','logo_mono','product','font','pattern','other')", name="kind_valid"
        ),
        Index("ix_brand_assets_brand_profile_id", "brand_profile_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(BigInteger)


class BrandChunkRow(Timestamps, Entity):
    __tablename__ = "brand_chunks"
    __table_args__ = (
        UniqueConstraint("brand_document_id", "chunk_index"),
        # Retrieval always filters by brand first, then ranks by distance, so
        # the brand column is what the scan needs to be cheap.
        Index("ix_brand_chunks_brand_profile_id", "brand_profile_id"),
        # Declared here, not only in migration 002: an index the ORM does not
        # know about looks like an orphan to `alembic autogenerate`, which
        # duly proposed dropping it while generating migration 003.
        Index(
            "ix_brand_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False
    )
    brand_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))


class BrandFactRow(TimestampsWithUpdate, Entity):
    """An AI-proposed brand fact. Never merged into `brand_profiles.payload`
    until a human accepts it (domain.brand.ExtractedFact)."""

    __tablename__ = "brand_facts"
    __table_args__ = (
        CheckConstraint("status in ('proposed','accepted','rejected')", name="status_valid"),
        CheckConstraint("confidence >= 0 and confidence <= 1", name="confidence_range"),
        Index("ix_brand_facts_brand_profile_id_status", "brand_profile_id", "status"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False
    )
    #: Null when the fact came from the onboarding form rather than a document.
    brand_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_documents.id", ondelete="SET NULL")
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")
    provenance: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Milestone 3 — campaign discovery
#
# Only what discovery needs. Creative directions, specifications, prompts and
# generated assets belong to Milestones 5+ and are not created here.
# ---------------------------------------------------------------------------
class CampaignRow(TimestampsWithUpdate, Entity):
    __tablename__ = "campaigns"
    __table_args__ = (
        # Generated from `CampaignRecordStatus` rather than restated here, so
        # adding a status to the enum without a migration fails loudly at
        # `alembic check` instead of silently at the first insert.
        CheckConstraint(
            "status in (" + ",".join(f"'{s.value}'" for s in CampaignRecordStatus) + ")",
            name="status_valid",
        ),
        Index("ix_campaigns_organization_id", "organization_id"),
        Index("ix_campaigns_brand_profile_id", "brand_profile_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    #: The brand this campaign speaks for. Required: a campaign without a brand
    #: has no Brand Brain to draw on, which is the whole point of discovery.
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_profiles.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DRAFT")
    #: The LangGraph thread. Equal to the campaign id as text — one campaign is
    #: one durable conversation (ADR-003). Derived from this scope-checked row,
    #: never from a request parameter (M1_SECURITY_AUDIT A-5).
    thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: Structured campaign inputs while the interview is still running. They
    #: have nowhere else to live until a specification exists
    #: (ARCHITECTURE_REVIEW M-1).
    draft_inputs: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    #: The validated `domain.reference.CreativePreferences`. A column rather
    #: than a table: there is exactly one preference set per campaign, and a
    #: table would add a join for nothing.
    creative_preferences: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignRunRow(Timestamps, Entity):
    """One graph execution. Drives the progress indicator and makes a stuck run
    visible rather than silent (ARCHITECTURE §6)."""

    __tablename__ = "campaign_runs"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING','RUNNING','WAITING_HUMAN','COMPLETED','FAILED','CANCELLED')",
            name="status_valid",
        ),
        Index("ix_campaign_runs_campaign_id_created_at", "campaign_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    current_node: Mapped[str | None] = mapped_column(Text)
    node_history: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignMessageRow(Timestamps, Entity):
    """The interview transcript. Product state, queryable without touching the
    checkpoint (ADR-004)."""

    __tablename__ = "campaign_messages"
    __table_args__ = (
        CheckConstraint("role in ('user','assistant','system')", name="role_valid"),
        # Ordering key. `created_at` alone is not enough: a question and its
        # answer are written in one flush and share a `now()`, so the tiebreak
        # fell to a random UUID and the transcript could render the answer
        # before the question.
        UniqueConstraint("campaign_id", "sequence"),
        Index("ix_campaign_messages_campaign_id_sequence", "campaign_id", "sequence"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    #: Monotonic within a campaign. The transcript's true order.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which field this turn was about, so the UI can show progress and the
    #: interviewer can avoid re-asking.
    targets_field: Mapped[str | None] = mapped_column(Text)
    question_metadata: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )


class CampaignSpecificationRow(TimestampsWithUpdate, Entity):
    """The CAMPAIGN SPECIFICATION — the source of truth for everything after.

    Versioned: an edit or a recompilation creates a new version rather than
    overwriting, so "what did we agree to" stays answerable.
    """

    __tablename__ = "campaign_specifications"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version"),
        Index("ix_campaign_specifications_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.campaign.CampaignBrief` (= Campaign Specification).
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class CampaignReferenceRow(Timestamps, Entity):
    """Creative inspiration for **one campaign**.

    Deliberately not a brand asset. A brand asset says "this is our approved
    visual identity"; a campaign reference says "this is inspiration for this
    campaign". Conflating them would let one campaign's mood board silently
    become brand truth, so they are separate tables with separate owners.
    """

    __tablename__ = "campaign_references"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING','ANALYZING','COMPLETED','FAILED')", name="status_valid"
        ),
        Index("ix_campaign_references_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(Text, comment="What the user liked about it.")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)

    # --- Milestone 4: reference intelligence ---------------------------
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    #: The validated `domain.reference.ReferenceAnalysis`.
    analysis: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Sanitised. A raw provider exception never reaches this column.
    error: Mapped[str | None] = mapped_column(Text)
    #: Lets a re-upload of identical bytes reuse the existing analysis rather
    #: than paying a multimodal call again.
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    #: A human reviewed and accepted the analysis.
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Milestone 5 — Creative Director
#
# Directions are stored as a versioned *set*, not as loose rows: three options
# are a single artefact a human chooses between, and a revision produces a new
# set rather than mutating the old one. That is what keeps "what did we reject,
# and why" answerable.
#
# No image-generation tables: those belong to Milestone 6.
# ---------------------------------------------------------------------------
class CreativeDirectionSetRow(TimestampsWithUpdate, Entity):
    __tablename__ = "creative_direction_sets"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version"),
        Index("ix_creative_direction_sets_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.creative.CreativeDirectionSet`.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The direction the human chose, once they have.
    selected_direction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreativeSpecificationRow(TimestampsWithUpdate, Entity):
    """The approved execution plan. Milestone 6 compiles prompts from this."""

    __tablename__ = "creative_specifications"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version"),
        Index("ix_creative_specifications_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    #: Null only if the owning set were deleted; normally the chosen direction.
    direction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.creative.CreativeSpecification`.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class CreativeApprovalRow(Timestamps, Entity):
    """Every human decision at a creative gate. Append-only audit trail."""

    __tablename__ = "creative_approvals"
    __table_args__ = (
        CheckConstraint("gate in ('strategy','specification')", name="gate_valid"),
        CheckConstraint(
            "decision in ('APPROVE','REJECT','REQUEST_REVISION','EDIT')", name="decision_valid"
        ),
        Index("ix_creative_approvals_campaign_id_created_at", "campaign_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    gate: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    feedback: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class CreativeRevisionRow(Timestamps, Entity):
    """One round of feedback, as an explicit KEEP/CHANGE delta.

    History is never overwritten: a revision adds a row and a new direction
    set, so "what changed and why" stays answerable.
    """

    __tablename__ = "creative_revisions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "iteration"),
        Index("ix_creative_revisions_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The validated `domain.creative.CreativeRevisionDelta`.
    delta: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    from_version: Mapped[int | None] = mapped_column(Integer)
    to_version: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------------------
# Milestone 6 — prompt compilation and image generation
# ---------------------------------------------------------------------------
class CanonicalPromptRow(Timestamps, Entity):
    """A compiled prompt, provider-neutral.

    A build artefact of an approved Creative Specification, never a source of
    truth: `source_fingerprint` records exactly which specification fields it
    was built from, so a prompt whose source has moved on is detectable rather
    than merely stale-looking.
    """

    __tablename__ = "canonical_prompts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "version"),
        Index("ix_canonical_prompts_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    specification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.prompt.CanonicalPrompt`.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ModelPromptRow(Timestamps, Entity):
    """One provider's rendering of a canonical prompt.

    Unique per (canonical prompt, provider, model, version): recompiling for a
    provider adds a version rather than overwriting, so the exact text a job
    was charged for stays on record.
    """

    __tablename__ = "model_prompts"
    __table_args__ = (
        UniqueConstraint("canonical_prompt_id", "provider", "model", "version"),
        Index("ix_model_prompts_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    canonical_prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canonical_prompts.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.prompt.ModelPrompt`.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class GenerationJobRow(Timestamps, Entity):
    """One provider's attempt at one prompt.

    `idempotency_key` is unique: a replayed request finds the existing job
    instead of charging a provider twice. A deliberate retry increments
    `attempt`, which is part of the key, so it is a new job and a new charge —
    the distinction the user is making when they press Retry.
    """

    __tablename__ = "generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="status_valid",
        ),
        UniqueConstraint("idempotency_key"),
        Index("ix_generation_jobs_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_generation_jobs_batch_id", "batch_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    model_prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_prompts.id", ondelete="CASCADE"), nullable=False
    )
    specification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Groups the jobs one "generate creatives" request started.
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider_job_id: Mapped[str | None] = mapped_column(Text)
    #: The validated `domain.common.ExecutionError` — a user-safe message and a
    #: code. Never a raw provider payload or a traceback.
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeneratedAssetRow(Timestamps, Entity):
    """A generated visual plate.

    `kind` is explicit: a raw model output is a plate, not a brand-ready
    creative. The logo, headline, CTA and exact colours are applied later by
    the deterministic renderer (ADR-006), and a column that says so stops a
    later milestone quietly treating one as the other.
    """

    __tablename__ = "generated_assets"
    __table_args__ = (
        CheckConstraint("kind in ('VISUAL_PLATE','FINAL_COMPOSITION')", name="kind_valid"),
        Index("ix_generated_assets_campaign_id_created_at", "campaign_id", "created_at"),
        Index("ix_generated_assets_generation_job_id", "generation_job_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    generation_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    model_prompt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="VISUAL_PLATE")
    #: Generated, never derived from anything a user typed.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, default="image/png")
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    seed: Mapped[str | None] = mapped_column(Text)
    #: Safe provider metadata only — model version, finish reason, timings.
    meta: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# Milestone 7 — creative evaluation and selection
# ---------------------------------------------------------------------------
class CreativeEvaluationRow(Timestamps, Entity):
    """One asset's evaluation, and the job that produced it.

    Status lives on the evaluation rather than in a separate `evaluation_jobs`
    table: an evaluation *is* the unit of work, and a second table whose only
    purpose was to point at this one would add a join and a way for the two to
    disagree. `payload` is null until the work completes; a failure carries an
    `error` and no payload, which is what makes a partial batch legible.

    Unique on `(generated_asset_id, evaluator_version)`: re-running the same
    evaluator on the same asset updates in place, while a future `v2` evaluator
    writes a row *beside* `v1` rather than overwriting it — the whole point of
    recording a version is being able to compare the two without pretending
    they were equivalent.
    """

    __tablename__ = "creative_evaluations"
    __table_args__ = (
        UniqueConstraint("generated_asset_id", "evaluator_version"),
        CheckConstraint(
            "status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="status_valid",
        ),
        CheckConstraint(
            "disposition is null or disposition in ('PASS','NEEDS_REVIEW','REJECT')",
            name="disposition_valid",
        ),
        CheckConstraint(
            "overall_score is null or (overall_score >= 0 and overall_score <= 100)",
            name="score_range_valid",
        ),
        Index("ix_creative_evaluations_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    generated_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="CASCADE"), nullable=False
    )
    #: The plan the *asset* was generated from — never a later approved
    #: revision. An evaluation against a plan the asset never saw is worthless.
    specification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evaluator_version: Mapped[str] = mapped_column(Text, nullable=False)
    evaluator_model: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    #: Denormalised from the payload so ranking and filtering are index-friendly
    #: without parsing JSON. Written only together with the payload.
    overall_score: Mapped[float | None] = mapped_column(Float)
    disposition: Mapped[str | None] = mapped_column(Text)
    #: The validated `domain.evaluation.CreativeEvaluation`. Null until done.
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: A user-safe `ExecutionError`. Never a raw provider payload.
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreativeSelectionRow(Timestamps, Entity):
    """The human's final choice of creative.

    Append-only: a change of mind adds a row, and the current selection is the
    most recent one. History costs one index and answers "what did they pick
    first, and when did they change it?" — which a single mutated row cannot.

    The evaluation is recorded alongside so a later milestone can say *why*
    this one was chosen, but it is nullable: a human may override the ranking
    entirely, and the product must let them.
    """

    __tablename__ = "creative_selections"
    __table_args__ = (
        Index("ix_creative_selections_campaign_id_created_at", "campaign_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    generated_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="CASCADE"), nullable=False
    )
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("creative_evaluations.id", ondelete="SET NULL")
    )
    selected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Why, in the human's own words. Optional.
    note: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------
# Milestone 8 — Brand Guardian and the revision loop
# ---------------------------------------------------------------------------
class BrandGuardianResultRow(Timestamps, Entity):
    """One asset's brand check, and the job that produced it.

    The same shape as `creative_evaluations`, for the same reason: the check is
    the unit of work, so its status lives on it rather than in a second table
    that could disagree. A `NEEDS_REVISION` verdict is a completed check with a
    finding, not a failure — `status` is about whether the *check ran*, and
    `verdict` is about what it found.

    Unique on `(generated_asset_id, guardian_version)`: re-running the same
    guardian updates in place, and a future `v2` writes a row beside `v1`.
    """

    __tablename__ = "brand_guardian_results"
    __table_args__ = (
        UniqueConstraint("generated_asset_id", "guardian_version"),
        CheckConstraint(
            "status in ('PENDING','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="status_valid",
        ),
        CheckConstraint(
            "verdict is null or verdict in ('PASS','NEEDS_REVISION','REJECT','UNKNOWN')",
            name="verdict_valid",
        ),
        Index("ix_brand_guardian_results_campaign_id", "campaign_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    generated_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="CASCADE"), nullable=False
    )
    #: The plan the asset came from — never a later revision.
    specification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    guardian_version: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_model: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    #: Denormalised from the payload so a gallery can filter without parsing
    #: JSON. Written only together with the payload.
    verdict: Mapped[str | None] = mapped_column(Text)
    #: The validated `domain.guardian.BrandGuardianResult`. Null until done.
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: A user-safe `ExecutionError`. Never a raw provider payload.
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SpecificationRevisionRow(Timestamps, Entity):
    """One round of feedback on a *creative specification*.

    Distinct from `creative_revisions`, which Milestone 5 uses for revisions of
    a *direction set*: that table's `from_version`/`to_version` count direction
    set versions, and putting specification versions in the same columns would
    mean two different version spaces sharing one name. Same pattern, different
    artefact, so a separate table rather than a discriminator column.

    History is append-only and never overwritten. `from_version` always points
    at a specification that still exists and still says what it said; the
    assets generated from it keep pointing at it.
    """

    __tablename__ = "specification_revisions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "iteration"),
        CheckConstraint(
            "status in ('PROPOSED','APPLIED','APPROVED','REJECTED')", name="status_valid"
        ),
        Index("ix_specification_revisions_campaign_id_iteration", "campaign_id", "iteration"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PROPOSED")
    #: The human's own words. A first-class revision input, not a log line.
    user_feedback: Mapped[str] = mapped_column(Text, nullable=False)
    #: The validated `domain.revision.RevisionDelta`, as approved.
    delta: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    #: What actually differed between the two versions, computed by the
    #: application service rather than taken from the delta's intent.
    changed_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Null until the delta is approved and applied.
    to_version: Mapped[int | None] = mapped_column(Integer)
    #: The asset whose review prompted this. History, not a dependency — it may
    #: be deleted without invalidating the revision it inspired.
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="SET NULL")
    )
    #: What was on the table when the human asked. Provenance for "this was
    #: revised because the guardian flagged product prominence".
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("creative_evaluations.id", ondelete="SET NULL")
    )
    guardian_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_guardian_results.id", ondelete="SET NULL")
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


# ---------------------------------------------------------------------------
# Milestone 9 — final brand composition
# ---------------------------------------------------------------------------
class LayoutSpecRow(Timestamps, Entity):
    """The working composition for one campaign and channel.

    The **source of truth** for final composition: the rendered PNG is an
    output of this, never the thing that is edited. An edit writes a new
    version rather than updating in place, so the render that was signed off
    last week still has the recipe that produced it.
    """

    __tablename__ = "layout_specs"
    __table_args__ = (
        UniqueConstraint("campaign_id", "channel", "version"),
        Index("ix_layout_specs_campaign_id_channel", "campaign_id", "channel"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The validated `domain.layout.LayoutSpec`.
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    #: Provenance: the plate this composes and the plan its copy came from.
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="SET NULL")
    )
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class FinalAssetRow(Timestamps, Entity):
    """A rendered, brand-composed, channel-sized deliverable.

    `layout_snapshot` carries the exact recipe inline as well as by id: a later
    edit to the layout must not silently change what an already-exported asset
    claims to be. The id says which document it came from; the snapshot says
    what it actually rendered.

    Never overwritten. A re-render adds a version, so an asset that has been
    sent to a client stays recoverable byte for byte.
    """

    __tablename__ = "final_assets"
    __table_args__ = (
        CheckConstraint("kind in ('FINAL_BRANDED_ASSET')", name="kind_valid"),
        UniqueConstraint("campaign_id", "channel", "version"),
        Index("ix_final_assets_campaign_id_created_at", "campaign_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    #: Only the deterministic composition pipeline writes this table, and the
    #: constraint says so — a generated plate can never be relabelled as a
    #: finished brand asset.
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="FINAL_BRANDED_ASSET")
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    layout_spec_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("layout_specs.id", ondelete="SET NULL")
    )
    layout_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The frozen recipe, exactly as rendered.
    layout_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_assets.id", ondelete="SET NULL")
    )
    specification_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    renderer_version: Mapped[str] = mapped_column(Text, nullable=False)

    #: Generated, never derived from anything a user typed.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, default="image/png")
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    rendered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
