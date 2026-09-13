"""The campaign command centre — a read model, and nothing else.

Every number on this page already exists somewhere. Discovery knows whether the
specification is confirmed, the creative stage knows which gate is open,
generation knows how its jobs ended, the evaluator knows the ranking, the
Guardian knows the verdict, and composition knows what has been rendered. This
module asks each of them and lays the answers out in one shape.

**It computes no state of its own.** That is the whole discipline here: a
dashboard that derives its own version of "is this campaign approved?" becomes a
second source of truth, and the first time the two disagree the dashboard is the
one people believe. So there is no table behind this, no cache, and no field
that is not read from the service that owns it.

The one thing it does add is *ordering*: the stages in the sequence the product
actually runs them, each with a state and a sentence. That is presentation, not
business logic, and it belongs here rather than in six separate screens.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import BrandGuardianResultRow, CampaignRow, FinalAssetRow
from app.domain.common import Channel
from app.domain.evaluation import EvaluationSummary
from app.domain.guardian import GuardianVerdict
from app.domain.workspace import Principal
from app.errors import NotFound
from app.providers.base import EmbeddingProvider, LLMProvider, StorageProvider
from app.repositories.brands import BrandRepository
from app.repositories.campaigns import CampaignRepository, CampaignSpecificationRepository
from app.repositories.creative import CreativeSpecificationRepository
from app.services.campaigns import STATUS_SPEC_CONFIRMED
from app.services.composition_stage import COMPOSABLE_CHANNELS, CompositionService
from app.services.evaluation_stage import EvaluationService
from app.services.generation import GenerationService
from app.services.revision_stage import RevisionStageService

#: The stages, in the order the product runs them. The key is stable (the UI
#: routes off it); the label is what a person reads.
STAGES: tuple[tuple[str, str], ...] = (
    ("discovery", "Campaign Specification"),
    ("creative", "Creative direction"),
    ("generation", "Creative generation"),
    ("evaluation", "Evaluation"),
    ("guardian", "Brand check"),
    ("composition", "Final asset"),
)

#: What a stage can be. `BLOCKED` means an earlier stage has not finished;
#: `ATTENTION` means this stage is waiting on a person.
PENDING = "PENDING"
BLOCKED = "BLOCKED"
ATTENTION = "ATTENTION"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"


@dataclass(frozen=True)
class StageState:
    key: str
    label: str
    state: str
    #: One sentence. What happened, or what is being waited on.
    detail: str


@dataclass(frozen=True)
class CampaignOverview:
    campaign_id: str
    title: str
    status: str
    brand_id: str
    brand_name: str

    stages: list[StageState] = field(default_factory=list)

    campaign_specification_version: int | None = None
    creative_specification_version: int | None = None
    creative_specification_approved: bool = False

    #: Successful plates in the *latest* batch, not the campaign total — a
    #: regenerated campaign has assets from rounds nobody is looking at.
    latest_batch_assets: int = 0
    failed_generations: int = 0

    evaluation: EvaluationSummary | None = None
    recommended_asset_id: str | None = None
    recommended_score: float | None = None
    recommended_reason: str = ""
    selected_asset_id: str | None = None

    guardian_verdict: str | None = None
    guardian_checked: int = 0

    revision_rounds: int = 0

    composed_channels: list[str] = field(default_factory=list)
    available_channels: list[str] = field(default_factory=list)
    final_assets: list[FinalAssetRow] = field(default_factory=list)
    latest_layout_version: int | None = None

    #: Where a person should go next, as a stage key. `None` when the campaign
    #: has nothing outstanding.
    next_stage: str | None = None
    next_action: str | None = None


class CampaignOverviewService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        settings: Settings,
        storage: StorageProvider,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.principal = principal
        self.settings = settings
        self.storage = storage
        self.llm = llm
        self.embeddings = embeddings
        self.organization_id = uuid.UUID(principal.organization_id)

    async def overview(self, campaign_id: uuid.UUID) -> CampaignOverview:
        campaign = await CampaignRepository(self.session, self.organization_id).get(campaign_id)
        if campaign is None:
            raise NotFound("Campaign not found.")
        brand = await BrandRepository(self.session, self.organization_id).get(
            campaign.brand_profile_id
        )

        discovery = await self._discovery(campaign)
        creative = await self._creative(campaign)
        generation = await self._generation(campaign)
        evaluation = await self._evaluation(campaign)
        guardian, revisions = await self._guardian(campaign)
        composition = await self._composition(campaign)

        stages = [
            _stage("discovery", discovery.state, discovery.detail),
            _stage("creative", creative.state, creative.detail),
            _stage("generation", generation.state, generation.detail),
            _stage("evaluation", evaluation.state, evaluation.detail),
            _stage("guardian", guardian.state, guardian.detail),
            _stage("composition", composition.state, composition.detail),
        ]
        nxt = next(
            (s for s in stages if s.state in (ATTENTION, FAILED, PENDING)),
            None,
        )

        summary = evaluation.summary
        recommendation = summary.recommendation if summary else None
        return CampaignOverview(
            campaign_id=str(campaign.id),
            title=campaign.title,
            status=campaign.status,
            brand_id=str(campaign.brand_profile_id),
            brand_name=brand.name if brand else "Unknown brand",
            stages=stages,
            campaign_specification_version=discovery.version,
            creative_specification_version=creative.version,
            creative_specification_approved=creative.approved,
            latest_batch_assets=generation.succeeded,
            failed_generations=generation.failed,
            evaluation=summary,
            recommended_asset_id=recommendation.generated_asset_id if recommendation else None,
            recommended_score=recommendation.overall_score if recommendation else None,
            recommended_reason=recommendation.reason if recommendation else "",
            selected_asset_id=summary.selected_asset_id if summary else None,
            guardian_verdict=guardian.verdict,
            guardian_checked=guardian.checked,
            revision_rounds=revisions,
            composed_channels=composition.composed,
            available_channels=[
                c.value for c in COMPOSABLE_CHANNELS if c.value not in composition.composed
            ],
            final_assets=composition.assets,
            latest_layout_version=composition.layout_version,
            next_stage=nxt.key if nxt else None,
            next_action=nxt.detail if nxt else None,
        )

    # ------------------------------------------------------------- per stage
    async def _discovery(self, campaign: CampaignRow) -> _Part:
        repo = CampaignSpecificationRepository(self.session, self.organization_id)
        latest = await repo.latest(campaign.id)
        if latest is None:
            return _Part(PENDING, "The interview has not started.", version=None)
        if campaign.status != STATUS_SPEC_CONFIRMED:
            return _Part(
                ATTENTION, "Review and confirm the Campaign Specification.", version=latest.version
            )
        return _Part(DONE, f"Confirmed at v{latest.version}.", version=latest.version)

    async def _creative(self, campaign: CampaignRow) -> _Part:
        if campaign.status != STATUS_SPEC_CONFIRMED:
            return _Part(BLOCKED, "Confirm the Campaign Specification first.")
        repo = CreativeSpecificationRepository(self.session, self.organization_id)
        latest = await repo.latest(campaign.id)
        if latest is None:
            return _Part(PENDING, "Generate creative directions.")
        if latest.approved_at is None:
            return _Part(
                ATTENTION,
                f"Approve Creative Specification v{latest.version}.",
                version=latest.version,
            )
        return _Part(
            DONE,
            f"Creative Specification v{latest.version} approved.",
            version=latest.version,
            approved=True,
        )

    async def _generation(self, campaign: CampaignRow) -> _Part:
        service = GenerationService(
            self.session,
            self.principal,
            settings=self.settings,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        )
        view = await service.current(campaign.id)
        batch = view.batch
        if batch is None:
            return _Part(
                BLOCKED if not view.can_generate else PENDING,
                view.blocked_reason or "Generate creatives from the approved plan.",
            )
        running = [j for j in batch.jobs if j.status.value in ("PENDING", "RUNNING")]
        failed = len(batch.failed)
        succeeded = len(batch.assets)
        if running:
            return _Part(RUNNING, f"{len(running)} job(s) still running.", succeeded, failed)
        if succeeded == 0:
            return _Part(FAILED, "Every generation job failed. Retry to continue.", 0, failed)
        return _Part(DONE, batch.outcome(), succeeded, failed)

    async def _evaluation(self, campaign: CampaignRow) -> _Part:
        service = EvaluationService(
            self.session,
            self.principal,
            settings=self.settings,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        )
        view = await service.current(campaign.id)
        summary = view.summary
        if view.in_flight:
            return _Part(RUNNING, f"{view.in_flight} evaluation(s) running.", summary=summary)
        if not summary.ranked and not summary.failed_asset_ids:
            return _Part(
                BLOCKED if not view.can_evaluate else PENDING,
                view.blocked_reason or "Score the generated creatives.",
                summary=summary,
            )
        if summary.selected_asset_id:
            return _Part(DONE, f"{summary.outcome()} A creative is selected.", summary=summary)
        return _Part(ATTENTION, f"{summary.outcome()} Choose one to take forward.", summary=summary)

    async def _guardian(self, campaign: CampaignRow) -> tuple[_Part, int]:
        service = RevisionStageService(
            self.session,
            self.principal,
            settings=self.settings,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        )
        view = await service.guardian_state(campaign.id)
        revision = await service.revision_state(campaign.id)
        # `history` is every revision row and `current` is the latest of them,
        # so adding them would count the newest round twice.
        rounds = len(revision.history)

        if revision.current is not None and revision.current.status in ("PROPOSED", "APPLIED"):
            return _Part(ATTENTION, "A revision is waiting for your approval."), rounds
        if view.in_flight:
            return _Part(RUNNING, f"{view.in_flight} brand check(s) running."), rounds
        if not view.results:
            return _Part(
                BLOCKED if not view.can_check else PENDING,
                view.blocked_reason or "Run the Brand Guardian.",
            ), rounds

        checked = len(view.results)
        selected = await self._selected_asset_id(campaign)
        if selected is not None:
            # The headline is about the creative that is actually going out.
            # "2 of 3 passed" is not an answer to "is this campaign safe?" —
            # it depends entirely on which one was chosen.
            mine = next((r for r in view.results if str(r.generated_asset_id) == selected), None)
            if mine is None:
                return _Part(
                    ATTENTION,
                    "The selected creative has not been brand-checked yet.",
                    verdict=GuardianVerdict.UNKNOWN.value,
                    checked=checked,
                ), rounds
            return _verdict_part(GuardianVerdict(mine.verdict or "UNKNOWN"), checked, "selected"), (
                rounds
            )

        return _verdict_part(_worst_verdict(view.results), checked, "worst"), rounds

    async def _selected_asset_id(self, campaign: CampaignRow) -> str | None:
        from app.repositories.evaluation import CreativeSelectionRepository

        row = await CreativeSelectionRepository(self.session, self.organization_id).current(
            campaign.id
        )
        return str(row.generated_asset_id) if row else None

    async def _composition(self, campaign: CampaignRow) -> _Part:
        service = CompositionService(
            self.session, self.principal, settings=self.settings, storage=self.storage
        )
        view = await service.current(campaign.id, channel=Channel.INSTAGRAM_POST)
        assets = view.final_assets
        if not view.composed_channels:
            return _Part(
                BLOCKED if not view.can_compose else PENDING,
                view.blocked_reason or "Compose the final branded asset.",
                composed=[],
                assets=assets,
            )
        if not assets:
            return _Part(
                ATTENTION,
                "The layout is ready — render it to produce the deliverable.",
                composed=view.composed_channels,
                assets=assets,
                layout_version=view.layout.version if view.layout else None,
            )
        channels = len({a.channel for a in assets})
        noun = "channel" if channels == 1 else "channels"
        return _Part(
            DONE,
            f"{len(assets)} final asset(s) across {channels} {noun}.",
            composed=view.composed_channels,
            assets=assets,
            layout_version=view.layout.version if view.layout else None,
        )


# ---------------------------------------------------------------------------
@dataclass
class _Part:
    """One stage's answer, before it is flattened into the overview."""

    state: str
    detail: str
    succeeded: int = 0
    failed: int = 0
    version: int | None = None
    approved: bool = False
    summary: EvaluationSummary | None = None
    verdict: str | None = None
    checked: int = 0
    composed: list[str] = field(default_factory=list)
    assets: list[FinalAssetRow] = field(default_factory=list)
    layout_version: int | None = None


def _stage(key: str, state: str, detail: str) -> StageState:
    label = dict(STAGES)[key]
    return StageState(key=key, label=label, state=state, detail=detail)


def _verdict_part(verdict: GuardianVerdict, checked: int, scope: str) -> _Part:
    """One verdict, phrased for what it is actually about."""
    subject = "The selected creative" if scope == "selected" else "A creative"
    if verdict is GuardianVerdict.PASS:
        detail = (
            f"The selected creative passed. {checked} checked."
            if scope == "selected"
            else f"All {checked} creative(s) passed."
        )
        return _Part(DONE, detail, verdict=verdict.value, checked=checked)
    if verdict is GuardianVerdict.UNKNOWN:
        return _Part(
            ATTENTION,
            "A brand check did not complete. Retry it.",
            verdict=verdict.value,
            checked=checked,
        )
    wording = "needs revision" if verdict is GuardianVerdict.NEEDS_REVISION else "was rejected"
    return _Part(
        ATTENTION,
        f"{subject} {wording} — review the findings.",
        verdict=verdict.value,
        checked=checked,
    )


def _worst_verdict(results: list[BrandGuardianResultRow]) -> GuardianVerdict:
    """The strictest verdict across the checked creatives.

    A campaign is not "passing the brand check" because one of four creatives
    passed — the honest headline is the worst thing the Guardian found.
    """
    order = [
        GuardianVerdict.REJECT,
        GuardianVerdict.NEEDS_REVISION,
        GuardianVerdict.UNKNOWN,
        GuardianVerdict.PASS,
    ]
    found = {r.verdict for r in results}
    for verdict in order:
        if verdict.value in found:
            return verdict
    return GuardianVerdict.UNKNOWN
