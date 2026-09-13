"""Request and response shapes.

Responses reuse the domain models wherever the domain already defines the
concept (CLAUDE.md rule 3). Only genuinely API-shaped aggregates — things that
exist because HTTP needs them, like a paged envelope — are defined here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.domain.approval import ALLOWED_DECISIONS, Decision, Gate
from app.domain.brand import (
    BrandColor,
    BrandFieldStatus,
    BrandProduct,
    BrandProfile,
    BrandTypography,
    BrandVoice,
    DocumentStatus,
    FactStatus,
    Provenance,
)
from app.domain.campaign import CampaignBrief, CampaignInputs, InterviewQuestion
from app.domain.common import Channel, DomainModel, JobStatus, Role, StyleFamily
from app.domain.creative import (
    ChannelCopy,
    CreativeDirectionSet,
    CreativeSpecification,
    DiversityVerdict,
)
from app.domain.creative_context import CreativeContext
from app.domain.evaluation import Dimension, Disposition
from app.domain.generation import AssetKind
from app.domain.guardian import (
    CheckStatus,
    GuardianCheck,
    GuardianVerdict,
    Severity,
)
from app.domain.layout import FinalAssetKind, LayoutReport, LayoutSpec
from app.domain.prompt import CanonicalPrompt
from app.domain.reference import (
    CreativePreferences,
    ReferenceAnalysis,
    ReferenceStatus,
    StyleWeight,
)
from app.domain.revision import RevisionAction, RevisionStatus
from app.domain.workspace import Organization, Project, User


class OrganizationMembership(DomainModel):
    organization: Organization
    role: Role


class MeResponse(DomainModel):
    """Everything the shell needs to render before it knows anything else."""

    user: User
    organizations: list[OrganizationMembership]
    active_organization_id: str | None = None


class CreateOrganizationRequest(DomainModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class CreateProjectRequest(DomainModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class UpdateProjectRequest(DomainModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ProjectPage(DomainModel):
    items: list[Project]
    next_cursor: str | None = None


class HealthResponse(DomainModel):
    status: str
    database: str
    providers: dict[str, str]
    #: True when this instance declares itself a demonstration: every provider
    #: is mock and nothing reaches an external service. Surfaced so the
    #: interface can say so rather than leaving a viewer to guess whether what
    #: they are looking at is real output.
    demo_mode: bool = False


# ---------------------------------------------------------------------------
# Milestone 2 — Brand Brain
# ---------------------------------------------------------------------------
class CreateBrandRequest(DomainModel):
    """Onboarding. Only `name` is required — a brand is built up over time, and
    demanding a full identity up front is how onboarding forms get abandoned."""

    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    website: str | None = Field(default=None, max_length=500)
    positioning: str | None = Field(default=None, max_length=2000)
    mission: str | None = Field(default=None, max_length=2000)
    audience_description: str | None = Field(default=None, max_length=2000)
    values: list[str] = Field(default_factory=list, max_length=20)
    voice: BrandVoice = Field(default_factory=BrandVoice)
    colors: list[BrandColor] = Field(default_factory=list, max_length=20)
    typography: BrandTypography = Field(default_factory=BrandTypography)
    preferred_styles: list[StyleFamily] = Field(default_factory=list)
    products: list[BrandProduct] = Field(default_factory=list, max_length=50)
    approved_claims: list[str] = Field(default_factory=list, max_length=50)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=50)
    visual_dos: list[str] = Field(default_factory=list, max_length=30)
    visual_donts: list[str] = Field(default_factory=list, max_length=30)
    logo_rules: list[str] = Field(default_factory=list, max_length=30)
    legal_line: str | None = Field(default=None, max_length=500)


class UpdateBrandRequest(DomainModel):
    """Partial. Every field optional; absent keys are left untouched."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    website: str | None = Field(default=None, max_length=500)
    positioning: str | None = Field(default=None, max_length=2000)
    mission: str | None = Field(default=None, max_length=2000)
    audience_description: str | None = Field(default=None, max_length=2000)
    values: list[str] | None = Field(default=None, max_length=20)
    voice: BrandVoice | None = None
    colors: list[BrandColor] | None = Field(default=None, max_length=20)
    typography: BrandTypography | None = None
    preferred_styles: list[StyleFamily] | None = None
    products: list[BrandProduct] | None = Field(default=None, max_length=50)
    approved_claims: list[str] | None = Field(default=None, max_length=50)
    prohibited_claims: list[str] | None = Field(default=None, max_length=50)
    visual_dos: list[str] | None = Field(default=None, max_length=30)
    visual_donts: list[str] | None = Field(default=None, max_length=30)
    logo_rules: list[str] | None = Field(default=None, max_length=30)
    legal_line: str | None = Field(default=None, max_length=500)


class BrandList(DomainModel):
    items: list[BrandProfile]


class BrandDocumentSummary(DomainModel):
    """What the documents panel renders. Status is explicit so a failure names
    the stage it failed at rather than showing an unexplained spinner."""

    id: str
    brand_id: str
    title: str
    source_type: str
    filename: str | None = None
    mime_type: str | None = None
    bytes: int | None = None
    status: DocumentStatus
    page_count: int | None = None
    chunk_count: int = 0
    error: str | None = None
    created_at: datetime


class DocumentList(DomainModel):
    items: list[BrandDocumentSummary]


class BrandAssetSummary(DomainModel):
    id: str
    brand_id: str
    kind: str
    filename: str | None = None
    mime_type: str
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    url: str


class AssetList(DomainModel):
    items: list[BrandAssetSummary]


class CreateTextDocumentRequest(DomainModel):
    """Pasted text — the path that needs no file at all."""

    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=200_000)


class FactSummary(DomainModel):
    id: str
    field: str
    value: str
    confidence: float
    status: FactStatus
    provenance: Provenance
    rationale: str | None = None


class FactList(DomainModel):
    items: list[FactSummary]


class FactDecisionRequest(DomainModel):
    """Accepting a proposal is the only way AI output becomes a brand fact."""

    status: FactStatus


class KnowledgeQuery(DomainModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)


class KnowledgeHit(DomainModel):
    chunk_id: str
    document_id: str
    document_title: str
    content: str
    score: float
    chunk_index: int
    page: int | None = None


class KnowledgeResult(DomainModel):
    query: str
    hits: list[KnowledgeHit]


class BrandBrainView(DomainModel):
    """Everything the Brand Brain page needs, in one call."""

    brand: BrandProfile
    documents: list[BrandDocumentSummary]
    assets: list[BrandAssetSummary]
    proposed_facts: list[FactSummary]
    field_status: list[BrandFieldStatus]
    chunk_count: int
    knowledge_ready: bool
    #: Populated when a stage failed, so the UI can say what to retry.
    processing_errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Milestone 3 — campaign discovery
# ---------------------------------------------------------------------------
class CreateCampaignRequest(DomainModel):
    brand_id: str
    title: str = Field(min_length=1, max_length=200)
    project_id: str | None = None


class CampaignSummary(DomainModel):
    id: str
    organization_id: str
    brand_id: str
    project_id: str | None = None
    title: str
    status: str
    created_at: datetime


class CampaignList(DomainModel):
    items: list[CampaignSummary]


class AnswerRequest(DomainModel):
    answer: str = Field(min_length=1, max_length=4000)


class DiscoveryTurnResponse(DomainModel):
    """One turn of the interview, plus everything the page needs to render."""

    campaign_id: str
    status: str
    question: InterviewQuestion | None = None
    missing: list[str] = Field(default_factory=list)
    turn: int = 0
    interview_complete: bool = False
    #: The Campaign Specification, once discovery has produced one.
    specification: CampaignBrief | None = None
    known: CampaignInputs


class CampaignMessageView(DomainModel):
    id: str
    role: str
    content: str
    targets_field: str | None = None
    created_at: datetime


class ConversationView(DomainModel):
    items: list[CampaignMessageView]


class UpdateSpecificationRequest(DomainModel):
    """Human edits. Every field optional; only what is sent is changed, and
    each edited field is marked so recompilation cannot undo it."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    audience: str | None = Field(default=None, min_length=1, max_length=2000)
    audience_insight: str | None = Field(default=None, max_length=2000)
    product: str | None = Field(default=None, min_length=1, max_length=500)
    key_message: str | None = Field(default=None, min_length=1, max_length=1000)
    supporting_messages: list[str] | None = Field(default=None, max_length=10)
    cta: str | None = Field(default=None, min_length=1, max_length=300)
    region: str | None = Field(default=None, max_length=200)
    channels: list[Channel] | None = Field(default=None, max_length=10)
    tone: list[str] | None = Field(default=None, max_length=10)
    desired_emotional_response: str | None = Field(default=None, max_length=500)
    campaign_tone: list[str] | None = Field(default=None, max_length=10)
    key_offer: str | None = Field(default=None, max_length=1000)
    timing_occasion: str | None = Field(default=None, max_length=300)
    required_elements: list[str] | None = Field(default=None, max_length=20)
    avoid_restrictions: list[str] | None = Field(default=None, max_length=20)
    constraints: list[str] | None = Field(default=None, max_length=20)


class CampaignReferenceView(DomainModel):
    id: str
    filename: str | None = None
    mime_type: str
    bytes: int | None = None
    note: str | None = None
    url: str
    # --- Milestone 4 ---------------------------------------------------
    status: ReferenceStatus = ReferenceStatus.PENDING
    analysis: ReferenceAnalysis | None = None
    error: str | None = None
    accepted: bool = False


class ReferenceList(DomainModel):
    items: list[CampaignReferenceView]


# ---------------------------------------------------------------------------
# Milestone 4 — reference intelligence
# ---------------------------------------------------------------------------
class SetPreferencesRequest(DomainModel):
    """Visual calibration. Picks are explicit; weights are derived."""

    selected_styles: list[StyleFamily] = Field(default_factory=list, max_length=8)
    liked_reference_ids: list[str] = Field(default_factory=list, max_length=20)
    disliked_reference_ids: list[str] = Field(default_factory=list, max_length=20)
    color_preference: list[str] = Field(default_factory=list, max_length=8)
    avoid: list[str] = Field(default_factory=list, max_length=10)
    free_text: str | None = Field(default=None, max_length=1000)


class StyleOption(DomainModel):
    """One choice in the visual calibration picker."""

    style: StyleFamily
    label: str
    description: str


class StyleOptionList(DomainModel):
    items: list[StyleOption]


class PreferencesView(DomainModel):
    preferences: CreativePreferences
    #: Rendered weights, strongest first — what the UI shows as the profile.
    profile: list[StyleWeight] = Field(default_factory=list)
    summary: str


class CreativeContextView(DomainModel):
    """The assembled context, plus a one-line summary for the page header."""

    context: CreativeContext
    summary: str
    ready: bool


# ---------------------------------------------------------------------------
# Milestone 5 — Creative Director
# ---------------------------------------------------------------------------
class StrategyDecisionRequest(DomainModel):
    """Gate 1. `direction_id` is required to approve."""

    decision: Decision
    direction_id: str | None = None
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _legal_at_this_gate(self) -> StrategyDecisionRequest:
        allowed = ALLOWED_DECISIONS[Gate.STRATEGY]
        if self.decision not in allowed:
            names = ", ".join(d.value for d in allowed)
            raise ValueError(f"{self.decision} is not valid here. Allowed: {names}")
        return self


class SpecificationDecisionRequest(DomainModel):
    """Gate 2."""

    decision: Decision
    feedback: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _legal_at_this_gate(self) -> SpecificationDecisionRequest:
        allowed = ALLOWED_DECISIONS[Gate.SPECIFICATION]
        if self.decision not in allowed:
            names = ", ".join(d.value for d in allowed)
            raise ValueError(f"{self.decision} is not valid here. Allowed: {names}")
        return self


class UpdateCreativeSpecificationRequest(DomainModel):
    """Human edits. Only what is sent changes, and each edited field is marked
    so a regeneration cannot undo it.

    `channel_copy` is sent whole rather than per channel: it is a small map and
    a partial patch of a nested map is ambiguous about deletion. Only channels
    the Campaign Specification declares are accepted, and the edit is subject
    to the same Gate 2 approval as every other field on this object.
    """

    concept: str | None = Field(default=None, min_length=1, max_length=800)
    visual_story: str | None = Field(default=None, max_length=1200)
    emotional_angle: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, min_length=1, max_length=200)
    headline_guidance: str | None = Field(default=None, max_length=400)
    subhead: str | None = Field(default=None, max_length=300)
    cta: str | None = Field(default=None, min_length=1, max_length=120)
    cta_guidance: str | None = Field(default=None, max_length=400)
    visual_metaphor: str | None = Field(default=None, max_length=400)
    composition: str | None = Field(default=None, max_length=500)
    focal_point: str | None = Field(default=None, max_length=300)
    subject: str | None = Field(default=None, max_length=500)
    environment: str | None = Field(default=None, max_length=500)
    lighting: str | None = Field(default=None, max_length=400)
    camera: str | None = Field(default=None, max_length=200)
    color_direction: str | None = Field(default=None, max_length=400)
    product_integration: str | None = Field(default=None, max_length=500)
    people_guidance: str | None = Field(default=None, max_length=400)
    brand_integration: str | None = Field(default=None, max_length=500)
    channel_copy: dict[Channel, ChannelCopy] | None = Field(default=None, max_length=7)


class GenerationJobView(DomainModel):
    """One provider's attempt, as the generation screen reads it.

    `error` is the user-safe `ExecutionError` recorded on the job — a message
    and a stable code. A raw provider payload never reaches here.
    """

    id: str
    provider: str
    model: str
    status: JobStatus
    attempt: int
    can_retry: bool
    error_message: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class GeneratedAssetView(DomainModel):
    """A generated plate, with everything needed to display and trace it."""

    id: str
    generation_job_id: str
    provider: str
    model: str
    #: `VISUAL_PLATE` — not a brand-ready creative (ADR-006).
    kind: AssetKind
    width: int
    height: int
    mime_type: str
    #: API path to the bytes. Served through the API so scope is always checked
    #: — the browser never addresses storage directly.
    url: str
    specification_version: int
    created_at: datetime


class ModelPromptView(DomainModel):
    """A compiled prompt, safe to show.

    `parameters` is deliberately absent: it is provider-specific, opaque
    outside `app/providers/`, and nothing the browser needs.
    """

    id: str
    provider: str
    model: str
    version: int
    text: str
    negative_text: str | None = None
    aspect_ratio: str
    specification_version: int
    trace: str


class GenerationView(DomainModel):
    """Where generation stands, in one call."""

    campaign_id: str
    batch_id: str | None = None
    #: Null until the first compile.
    canonical_prompt: CanonicalPrompt | None = None
    prompts: list[ModelPromptView] = Field(default_factory=list)
    jobs: list[GenerationJobView] = Field(default_factory=list)
    assets: list[GeneratedAssetView] = Field(default_factory=list)
    #: "2/3 providers succeeded — 1 failed."
    outcome: str = "Nothing generated yet."
    complete: bool = False
    specification_version: int | None = None
    can_generate: bool = False
    blocked_reason: str | None = None


# ---------------------------------------------------------------------------
# Milestone 7 — creative evaluation and selection
# ---------------------------------------------------------------------------
class DimensionScoreView(DomainModel):
    """One dimension, its score, and the line explaining it."""

    dimension: Dimension
    label: str
    score: int
    note: str = ""
    #: How much this dimension moved the overall score. Shown so a user can see
    #: why a weak dimension did or did not matter.
    weight: float


class EvaluationDetailView(DomainModel):
    """One asset's evaluation, as a human reads it.

    Carries no raw model output: `rationale`, `strengths` and `concerns` are the
    short user-facing summaries the evaluator produced, and nothing else.
    """

    id: str
    generated_asset_id: str
    status: JobStatus
    evaluator_version: str
    evaluator_model: str | None = None
    specification_version: int
    dimensions: list[DimensionScoreView] = Field(default_factory=list)
    overall_score: float | None = None
    disposition: Disposition | None = None
    #: The threshold rules that produced the disposition, in words.
    disposition_reasons: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    rationale: str = ""
    error_message: str | None = None
    error_code: str | None = None
    can_retry: bool = False
    evaluated_at: datetime | None = None


class RankedAssetView(DomainModel):
    """One row of the ranking, joined to the plate it describes."""

    rank: int
    generated_asset_id: str
    evaluation_id: str
    overall_score: float
    disposition: Disposition
    reason: str
    recommended: bool
    #: The asset itself, so the gallery needs one call rather than two.
    asset: GeneratedAssetView | None = None


class RecommendationView(DomainModel):
    generated_asset_id: str | None = None
    rank: int | None = None
    overall_score: float | None = None
    reason: str = ""
    #: Said out loud when the best available asset is not actually good.
    caveat: str | None = None


class EvaluationView(DomainModel):
    """Where evaluation stands, in one call."""

    campaign_id: str
    evaluator_version: str
    ranked: list[RankedAssetView] = Field(default_factory=list)
    recommendation: RecommendationView | None = None
    #: Every evaluation row, including failures — so nothing is a silent gap.
    evaluations: list[EvaluationDetailView] = Field(default_factory=list)
    #: "2/3 assets evaluated — 1 failed."
    outcome: str = "Nothing evaluated yet."
    #: Still PENDING or RUNNING. The client polls while this is non-zero.
    in_flight: int = 0
    unevaluated_asset_ids: list[str] = Field(default_factory=list)
    selected_asset_id: str | None = None
    can_evaluate: bool = False
    blocked_reason: str | None = None


class StartEvaluationRequest(DomainModel):
    """Evaluate everything, or just the assets named."""

    asset_ids: list[str] | None = None


class SelectCreativeRequest(DomainModel):
    """The human's final choice."""

    generated_asset_id: str
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Milestone 8 — Brand Guardian and the revision loop
# ---------------------------------------------------------------------------
class GuardianCheckView(DomainModel):
    """One check, its outcome, and what would fix it."""

    check: GuardianCheck
    label: str
    status: CheckStatus
    severity: Severity | None = None
    detail: str = ""
    suggested_fix: str | None = None
    #: True when code decided this, not a model. Shown, because the two carry
    #: different weight.
    deterministic: bool = False


class GuardianResultView(DomainModel):
    """One asset's brand check, whatever state it is in."""

    id: str
    generated_asset_id: str
    status: JobStatus
    guardian_version: str
    guardian_model: str | None = None
    specification_version: int
    verdict: GuardianVerdict | None = None
    checks: list[GuardianCheckView] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    error_message: str | None = None
    error_code: str | None = None
    can_retry: bool = False
    evaluated_at: datetime | None = None
    asset: GeneratedAssetView | None = None


class GuardianView(DomainModel):
    """Where the brand check stands, in one call."""

    campaign_id: str
    guardian_version: str
    results: list[GuardianResultView] = Field(default_factory=list)
    in_flight: int = 0
    unchecked_asset_ids: list[str] = Field(default_factory=list)
    can_check: bool = False
    blocked_reason: str | None = None


class StartGuardianRequest(DomainModel):
    asset_ids: list[str] | None = None


class FieldChangeView(DomainModel):
    field: str
    label: str
    action: RevisionAction
    reason: str
    new_value: str | None = None
    #: What the field says now, so the UI can show before and after.
    current_value: str | None = None


class RevisionDeltaView(DomainModel):
    """The proposal a human reads before approving it."""

    iteration: int
    user_feedback: str
    interpretation: str = ""
    keep: list[str] = Field(default_factory=list)
    change: list[FieldChangeView] = Field(default_factory=list)
    add: list[FieldChangeView] = Field(default_factory=list)
    remove: list[FieldChangeView] = Field(default_factory=list)
    explicit_unlocks: list[str] = Field(default_factory=list)
    #: Why this revision was proposed. Never a reasoning trace.
    rationale: str = ""


class SpecificationDiffView(DomainModel):
    """One field, before and after. The whole of what approval means."""

    field: str
    label: str
    before: str
    after: str


class RevisionRecordView(DomainModel):
    id: str
    iteration: int
    status: RevisionStatus
    user_feedback: str
    delta: RevisionDeltaView
    changed_fields: list[str] = Field(default_factory=list)
    from_version: int
    to_version: int | None = None
    source_asset_id: str | None = None
    created_at: datetime


class RevisionView(DomainModel):
    """Where the revision loop stands, in one call."""

    campaign_id: str
    #: The round waiting on a human, if any.
    current: RevisionRecordView | None = None
    history: list[RevisionRecordView] = Field(default_factory=list)
    #: Before and after, once the delta has been applied.
    diff: list[SpecificationDiffView] = Field(default_factory=list)
    can_revise: bool = False
    blocked_reason: str | None = None


class ProposeRevisionRequest(DomainModel):
    """Natural language stays primary — no structured form is required."""

    feedback: str = Field(min_length=1, max_length=2000)
    #: The creative the feedback is about, when the user was looking at one.
    source_asset_id: str | None = None


class EditFieldChangeRequest(DomainModel):
    field: str = Field(min_length=1, max_length=60)
    action: RevisionAction = RevisionAction.CHANGE
    reason: str = Field(default="Edited by a human.", max_length=300)
    new_value: str | None = Field(default=None, max_length=1200)


class EditRevisionDeltaRequest(DomainModel):
    """A human's edit of the proposed plan. Re-validated server-side: an edit
    must not become the way around the rules the planner enforces."""

    interpretation: str = Field(default="", max_length=600)
    keep: list[str] = Field(default_factory=list, max_length=40)
    change: list[EditFieldChangeRequest] = Field(default_factory=list, max_length=20)
    add: list[EditFieldChangeRequest] = Field(default_factory=list, max_length=10)
    remove: list[EditFieldChangeRequest] = Field(default_factory=list, max_length=10)
    rationale: str = Field(default="", max_length=600)


class CreativeStageView(DomainModel):
    """Where the creative stage stands, in one call."""

    campaign_id: str
    #: "strategy_gate" | "specification_gate" | null when nothing is pending.
    gate: str | None = None
    direction_set: CreativeDirectionSet | None = None
    selected_direction_id: str | None = None
    specification: CreativeSpecification | None = None
    diversity: DiversityVerdict | None = None
    approved: bool = False
    gaps: list[str] = Field(default_factory=list)
    #: Channels the Campaign Specification declares — the only ones a
    #: per-channel copy override may name.
    channels: list[Channel] = Field(default_factory=list)


# --------------------------------------------------------------- composition
class FinalAssetView(DomainModel):
    """A rendered deliverable, with the provenance that makes it traceable.

    Every field after `url` answers "what exactly produced this file?" — the
    campaign, the plate, the approved specification version, the layout version
    and the renderer version. Without those, a PNG in a folder is untraceable.
    """

    id: str
    campaign_id: str
    channel: Channel
    #: Always `FINAL_BRANDED_ASSET`. A generated plate is a different thing and
    #: is never labelled this way (ADR-006).
    kind: FinalAssetKind
    version: int
    width: int
    height: int
    mime_type: str
    size_bytes: int | None = None
    #: API path to the bytes. Served through the API so scope is checked on
    #: every read — the browser never addresses storage directly.
    url: str
    source_asset_id: str | None = None
    specification_version: int
    layout_version: int
    renderer_version: str
    created_at: datetime


class FinalAssetList(DomainModel):
    items: list[FinalAssetView]
    total: int


class CompositionView(DomainModel):
    """Where final composition stands for one channel."""

    campaign_id: str
    channel: Channel
    #: The source of truth. The rendered image is an output of this.
    layout: LayoutSpec | None = None
    #: Computed geometry check — why a render is blocked, in plain words.
    report: LayoutReport | None = None
    #: Newest first, every channel. History is never overwritten.
    final_assets: list[FinalAssetView] = Field(default_factory=list)
    composed_channels: list[Channel] = Field(default_factory=list)
    #: Channels that could still be added as variants.
    available_channels: list[Channel] = Field(default_factory=list)
    can_compose: bool = False
    blocked_reason: str | None = None


class ElementEditRequest(DomainModel):
    """What the constrained editor may change about one element.

    Deliberately small. This is a composition tool: it moves, resizes,
    restyles, rewrites and hides what the layout already has. It does not draw,
    animate, add pages or introduce new element types.
    """

    content: str | None = Field(default=None, max_length=300)
    visible: bool | None = None
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    width: float | None = Field(default=None, gt=0.0, le=1.0)
    height: float | None = Field(default=None, gt=0.0, le=1.0)
    size: float | None = Field(default=None, gt=0.0, le=0.5)
    align: str | None = Field(default=None, max_length=10)
    color: str | None = Field(default=None, max_length=7)
    uppercase: bool | None = None

    def changes(self) -> dict[str, object]:
        """Only what the caller actually sent.

        A field left out is "unchanged", never "set to null" — otherwise a UI
        that posts one property would blank every other one.
        """
        return self.model_dump(exclude_unset=True, exclude_none=True)


class LayoutEditRequest(DomainModel):
    """One accepted edit. Applied as a new layout version, never in place."""

    elements: dict[str, ElementEditRequest] = Field(default_factory=dict, max_length=40)
    background_color: str | None = Field(default=None, max_length=7)

    @model_validator(mode="after")
    def _not_empty(self) -> LayoutEditRequest:
        if not self.elements and self.background_color is None:
            raise ValueError("an edit must change something")
        return self


class ComposeRequest(DomainModel):
    """Build the default layout for a channel."""

    channel: Channel = Channel.INSTAGRAM_POST


class VariantRequest(DomainModel):
    """Re-lay an existing composition into another frame.

    A re-layout, never a regeneration: same plate, same approved copy, same
    logo. Only the geometry changes.
    """

    channel: Channel
    source: Channel = Channel.INSTAGRAM_POST


class RenderRequest(DomainModel):
    """Render the current layout and store it as a new final asset."""

    channel: Channel = Channel.INSTAGRAM_POST
    #: PNG keeps the sharp text edges the renderer works hard for; JPEG exists
    #: because some ad platforms still insist on it. Nothing else — print and
    #: PDF are explicitly out of scope.
    format: str = Field(default="PNG", pattern="^(PNG|JPEG)$")


# ------------------------------------------------------------ command centre
class StageStateView(DomainModel):
    """One stage of the campaign, as the overview shows it."""

    key: str
    label: str
    #: PENDING | BLOCKED | ATTENTION | RUNNING | DONE | FAILED
    state: str
    detail: str


class CampaignOverviewView(DomainModel):
    """The command centre: every stage of one campaign, in one call.

    A read model. Nothing here is stored — each field is read from the service
    that owns it, so the overview cannot drift from the screens it summarises.
    """

    campaign_id: str
    title: str
    status: str
    brand_id: str
    brand_name: str

    stages: list[StageStateView] = Field(default_factory=list)

    campaign_specification_version: int | None = None
    creative_specification_version: int | None = None
    creative_specification_approved: bool = False

    #: Successful plates in the latest generation batch, not the campaign
    #: total — a regenerated campaign has assets from earlier rounds.
    latest_batch_assets: int = 0
    failed_generations: int = 0

    recommended_asset_id: str | None = None
    recommended_score: float | None = None
    recommended_reason: str = ""
    selected_asset_id: str | None = None
    #: The ranking, so the overview can show the shortlist without a second
    #: call. The plate itself is not embedded — the gallery does that.
    ranked: list[RankedAssetView] = Field(default_factory=list)

    guardian_verdict: GuardianVerdict | None = None
    guardian_checked: int = 0
    revision_rounds: int = 0

    composed_channels: list[Channel] = Field(default_factory=list)
    available_channels: list[Channel] = Field(default_factory=list)
    final_assets: list[FinalAssetView] = Field(default_factory=list)
    latest_layout_version: int | None = None

    #: The stage a person should go to next, or null when nothing is waiting.
    next_stage: str | None = None
    next_action: str | None = None
