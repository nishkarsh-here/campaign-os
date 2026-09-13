"""CampaignState — the one canonical state object.

Every node reads from and writes to this. There are no side channels between
nodes (CLAUDE.md rule 4): if a node needs something, it is in state or it comes
from an injected provider.

Three rules that are not obvious and matter:

1. **Nodes return partial dicts, never a whole state.** A node computes its
   declared `writes` and returns only those keys. LangGraph merges via the
   reducers annotated below.
2. **State must stay JSON-serializable.** It is checkpointed to Postgres.
   Binary lives in storage; state carries `storage_key`s and URLs.
3. **Exactly one node owns each scalar field.** See `NODE_CONTRACTS` — the
   ownership table is enforced by a test, not by convention.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.approval import ApprovalDecision, PendingGate
from app.domain.brand import BrandAsset, BrandKnowledge, BrandProfile
from app.domain.campaign import CampaignBrief, CampaignInputs, ConversationTurn, InterviewQuestion
from app.domain.common import (
    CampaignStatus,
    ErrorSeverity,
    ExecutionError,
    JobStatus,
    Recommendation,
)
from app.domain.creative import (
    CreativeDirection,
    CreativeDirectionSet,
    CreativeRevisionDelta,
    CreativeSpecification,
)
from app.domain.creative_context import CreativeContext
from app.domain.evaluation import CreativeEvaluation, RankedAsset
from app.domain.generation import GeneratedAsset, GenerationJob
from app.domain.guardian import BrandGuardianResult
from app.domain.layout import ExportManifest, FinalAsset, LayoutSpec
from app.domain.market import MarketContext, RegionalContext
from app.domain.prompt import CanonicalPrompt, ModelPrompt
from app.domain.reference import (
    AggregateReferenceStyle,
    CampaignReference,
    CreativePreferences,
    ReferenceAnalysis,
)
from app.domain.revision import RevisionDelta, RevisionRecord
from app.domain.workspace import Organization, Project, User
from app.graph.reducers import append, merge_dict, upsert_by_id, upsert_on


class CampaignState(BaseModel):
    """Shared state for one campaign's graph execution.

    `thread_id` is the campaign id, so a campaign is one durable conversation
    that survives reloads and restarts (ADR-003).
    """

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=False)

    # --- identity / scope (set at START, never rewritten) ----------------
    campaign_id: str
    project_id: str
    user_id: str
    run_id: str | None = None

    project: Project | None = None
    organization: Organization | None = None
    user: User | None = None

    # --- brand brain -----------------------------------------------------
    brand: BrandProfile | None = None
    brand_assets: list[BrandAsset] = Field(default_factory=list)
    brand_knowledge: BrandKnowledge | None = None

    # --- interview -------------------------------------------------------
    conversation: Annotated[list[ConversationTurn], append] = Field(default_factory=list)
    campaign_inputs: CampaignInputs = Field(default_factory=CampaignInputs)
    pending_questions: list[InterviewQuestion] = Field(default_factory=list)
    interview_complete: bool = False
    #: Interview turns taken. Separate from `iteration_count` on purpose: a long
    #: interview must not consume the revision budget (ARCHITECTURE_REVIEW C-2).
    interview_turn_count: int = 0

    # --- inputs from the world -------------------------------------------
    references: list[CampaignReference] = Field(default_factory=list)
    #: Keyed by the reference, not by `id`: one analysis per reference.
    reference_analysis: Annotated[list[ReferenceAnalysis], upsert_on("reference_id")] = Field(
        default_factory=list
    )
    aggregate_style: AggregateReferenceStyle | None = None
    creative_preferences: CreativePreferences = Field(default_factory=CreativePreferences)
    market_context: MarketContext | None = None
    regional_context: RegionalContext | None = None

    # --- strategy --------------------------------------------------------
    campaign_brief: CampaignBrief | None = None
    #: The assembled Milestone 4 context. The Creative Director consumes this
    #: rather than re-deriving brand rules and preferences for itself.
    creative_context: CreativeContext | None = None
    #: The three options as one versioned artefact. Replaces the earlier
    #: `creative_directions` list plus `direction_recommendation`: three
    #: options and their recommendation are one thing a human chooses between,
    #: and splitting them across fields meant two owners for one concept.
    direction_set: CreativeDirectionSet | None = None
    selected_direction: CreativeDirection | None = None
    #: Set when a human asked for changes. Explicit KEEP/CHANGE, so a revision
    #: cannot quietly alter a campaign fact.
    creative_revision: CreativeRevisionDelta | None = None

    # --- creative specification and prompts -------------------------------
    creative_specification: CreativeSpecification | None = None
    canonical_prompt: CanonicalPrompt | None = None
    model_prompts: Annotated[list[ModelPrompt], upsert_by_id] = Field(default_factory=list)
    guardian_precheck: BrandGuardianResult | None = None
    precheck_attempts: int = 0

    # --- generation -------------------------------------------------------
    generation_jobs: Annotated[list[GenerationJob], upsert_by_id] = Field(default_factory=list)
    generated_assets: Annotated[list[GeneratedAsset], upsert_by_id] = Field(default_factory=list)
    providers_attempted: list[str] = Field(default_factory=list)

    # --- evaluation and governance ----------------------------------------
    evaluation_results: Annotated[list[CreativeEvaluation], upsert_by_id] = Field(
        default_factory=list
    )
    brand_guardian_results: Annotated[list[BrandGuardianResult], upsert_by_id] = Field(
        default_factory=list
    )
    ranked_assets: list[RankedAsset] = Field(default_factory=list)
    asset_recommendation: Recommendation | None = None

    # --- human in the loop -------------------------------------------------
    #: gate name -> the decision made there. Merged, so answering gate 3 never
    #: erases the record of gate 1.
    approval_states: Annotated[dict[str, ApprovalDecision], merge_dict] = Field(
        default_factory=dict
    )
    pending_gate: PendingGate | None = None
    user_feedback: str | None = None

    # --- revision ----------------------------------------------------------
    revision_delta: RevisionDelta | None = None
    revision_history: Annotated[list[RevisionRecord], append] = Field(default_factory=list)
    #: Revision iterations only. See `interview_turn_count`.
    iteration_count: int = 0

    # --- output -------------------------------------------------------------
    selected_asset: GeneratedAsset | None = None
    final_design: LayoutSpec | None = None
    final_assets: Annotated[list[FinalAsset], upsert_by_id] = Field(default_factory=list)
    export_manifest: ExportManifest | None = None

    # --- execution ------------------------------------------------------------
    status: CampaignStatus = CampaignStatus.DRAFT
    errors: Annotated[list[ExecutionError], append] = Field(default_factory=list)

    # ---------------------------------------------------------------- helpers
    # Read-only conveniences. They never mutate state — routing predicates and
    # nodes both use them so the same question is never answered two ways.

    def has_fatal_error(self) -> bool:
        return any(e.severity is ErrorSeverity.FATAL for e in self.errors)

    def assets_for_review(self) -> list[GeneratedAsset]:
        """Every asset that reached storage. A `GeneratedAsset` exists only for
        a job that completed, so there is nothing to filter — the name says so
        rather than implying a filter that is not applied."""
        return list(self.generated_assets)

    def failed_jobs(self) -> list[GenerationJob]:
        return [j for j in self.generation_jobs if j.status is JobStatus.FAILED]

    def can_iterate(self, maximum: int) -> bool:
        """Revision budget."""
        return self.iteration_count < maximum

    def can_ask_another_question(self, maximum: int) -> bool:
        """Interview budget — a separate allowance (see `interview_turn_count`)."""
        return self.interview_turn_count < maximum

    def decision_at(self, gate: str) -> ApprovalDecision | None:
        return self.approval_states.get(gate)


def initial_state(
    campaign_id: str, project_id: str, user_id: str, **overrides: Any
) -> CampaignState:
    """The only sanctioned way to construct a fresh state."""
    return CampaignState(
        campaign_id=campaign_id, project_id=project_id, user_id=user_id, **overrides
    )


#: Every field name, for contract validation.
STATE_FIELDS: frozenset[str] = frozenset(CampaignState.model_fields.keys())
