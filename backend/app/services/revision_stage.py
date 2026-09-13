"""The revision stage.

Runs the Brand Guardian over generated plates, turns human feedback into a
reviewable delta, applies it deterministically to produce the next Creative
Specification version, and hands that version to the *existing* generation and
evaluation machinery.

**Two human decisions, so two gates.** A delta is proposed and waits
(`PROPOSED`); the human approves or edits it, it is applied, and the revised
specification waits (`APPLIED`); the human approves that, and only then may
regeneration start (`APPROVED`). Both gates are explicit rows, not inferred
state — see ADR-013 for why they are not graph interrupts.

**Nothing here rewrites a specification.** `apply_revision` is a pure function
in its own module; this service supplies it with a delta a human approved and
stores what came back. A v1 row is never updated — v2 is a new row, and the
assets generated from v1 keep pointing at a v1 that still says what it said.

**Regeneration and re-evaluation are reused, not reimplemented.** Once a
revision is approved, `GenerationService` compiles prompts from the new version
and `EvaluationService` scores the resulting assets against it. Milestone 8
adds no second generation path.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    BrandGuardianResultRow,
    CampaignRow,
    GeneratedAssetRow,
    SpecificationRevisionRow,
)
from app.domain.campaign import CampaignBrief
from app.domain.common import ErrorSeverity, ExecutionError, JobStatus
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import CreativeContext
from app.domain.evaluation import EVALUATOR_VERSION, CreativeEvaluation
from app.domain.guardian import GUARDIAN_VERSION, BrandGuardianResult
from app.domain.revision import RevisionDelta, RevisionStatus
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound, ValidationFailed
from app.logging import get_logger
from app.providers.base import (
    EmbeddingProvider,
    ImageRef,
    LLMProvider,
    ProviderError,
    StorageProvider,
)
from app.providers.local.storage import StorageObjectNotFound
from app.repositories.campaigns import CampaignRepository, CampaignSpecificationRepository
from app.repositories.creative import CreativeSpecificationRepository
from app.repositories.evaluation import CreativeEvaluationRepository
from app.repositories.generation import GeneratedAssetRepository
from app.repositories.revision import (
    BrandGuardianRepository,
    SpecificationRevisionRepository,
)
from app.services.brand_guardian import (
    AssetNotCheckable,
    BrandGuardian,
    GuardianContext,
)
from app.services.evaluation_stage import _to_asset
from app.services.revision_application import apply_revision
from app.services.revision_planner import (
    FeedbackTooVague,
    RevisionContext,
    RevisionPlanner,
    validate_delta,
)

log = get_logger(__name__)


@dataclass(frozen=True)
class GuardianView:
    """Every brand check for a campaign, as the UI reads it."""

    campaign_id: str
    guardian_version: str
    results: list[BrandGuardianResultRow]
    in_flight: int
    unchecked_asset_ids: list[str]
    can_check: bool
    blocked_reason: str | None


@dataclass(frozen=True)
class RevisionView:
    """Where the revision loop stands."""

    campaign_id: str
    current: SpecificationRevisionRow | None
    history: list[SpecificationRevisionRow]
    #: The specification the open revision would produce, once applied.
    revised_specification: CreativeSpecification | None
    #: The version it was revised from, for a before/after diff.
    source_specification: CreativeSpecification | None
    can_revise: bool
    blocked_reason: str | None


class RevisionStageService:
    """The guardian, the planner, and the two human gates."""

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

        self.campaigns = CampaignRepository(session, self.organization_id)
        self.assets = GeneratedAssetRepository(session, self.organization_id)
        self.specifications = CreativeSpecificationRepository(session, self.organization_id)
        self.campaign_specifications = CampaignSpecificationRepository(
            session, self.organization_id
        )
        self.evaluations = CreativeEvaluationRepository(session, self.organization_id)
        self.guardians = BrandGuardianRepository(session, self.organization_id)
        self.revisions = SpecificationRevisionRepository(session, self.organization_id)
        self.guardian = BrandGuardian(llm)
        self.planner = RevisionPlanner(llm)

    # ---------------------------------------------------------- the guardian
    async def guardian_state(self, campaign_id: uuid.UUID) -> GuardianView:
        campaign = await self._campaign(campaign_id)
        assets = await self.assets.for_campaign(campaign.id)
        rows = await self.guardians.for_campaign(campaign.id, guardian_version=GUARDIAN_VERSION)
        checked = {str(row.generated_asset_id) for row in rows}
        return GuardianView(
            campaign_id=str(campaign.id),
            guardian_version=GUARDIAN_VERSION,
            results=rows,
            in_flight=sum(
                1
                for row in rows
                if row.status in (JobStatus.PENDING.value, JobStatus.RUNNING.value)
            ),
            unchecked_asset_ids=[str(a.id) for a in assets if str(a.id) not in checked],
            can_check=bool(assets),
            blocked_reason=None if assets else "Generate creatives before brand-checking them.",
        )

    async def start_guardian(
        self, campaign_id: uuid.UUID, *, asset_ids: list[uuid.UUID] | None = None
    ) -> tuple[GuardianView, list[uuid.UUID]]:
        """Claim a PENDING check per asset and return immediately."""
        campaign = await self._campaign(campaign_id)
        assets = await self._assets(campaign, asset_ids)
        if not assets:
            raise Conflict("There are no generated creatives to brand-check.")

        claimed: list[uuid.UUID] = []
        for asset in assets:
            row = await self.guardians.claim(
                campaign_id=campaign.id,
                generated_asset_id=asset.id,
                specification_id=asset.specification_id,
                specification_version=asset.specification_version,
                guardian_version=GUARDIAN_VERSION,
            )
            claimed.append(row.id)

        log.info(
            "guardian_batch_started",
            campaign_id=str(campaign.id),
            assets=len(claimed),
            guardian_version=GUARDIAN_VERSION,
        )
        return await self.guardian_state(campaign_id), claimed

    async def retry_guardian(self, campaign_id: uuid.UUID, result_id: uuid.UUID) -> uuid.UUID:
        campaign = await self._campaign(campaign_id)
        row = await self.guardians.get(result_id)
        if row is None or row.campaign_id != campaign.id:
            raise NotFound("Brand check not found.")
        if row.status != JobStatus.FAILED.value:
            raise Conflict("Only a failed brand check can be retried.")
        await self.guardians.claim(
            campaign_id=campaign.id,
            generated_asset_id=row.generated_asset_id,
            specification_id=row.specification_id,
            specification_version=row.specification_version,
            guardian_version=GUARDIAN_VERSION,
        )
        return row.id

    async def run_guardian_checks(self, result_ids: list[uuid.UUID]) -> None:
        """Sequential on this service's session; the concurrent path gives each
        check a session of its own (ADR-012)."""
        for result_id in result_ids:
            await self.run_guardian_check(result_id)

    async def run_guardian_check(self, result_id: uuid.UUID) -> None:
        """Check one plate. Never raises — a failure is a row, not an exception."""
        row = await self.guardians.get(result_id)
        if row is None or row.status != JobStatus.PENDING.value:
            return

        asset_row = await self.assets.get(row.generated_asset_id)
        if asset_row is None:
            await self.guardians.mark_failed(
                row, error=_error("The generated asset is missing.", code="ASSET_MISSING")
            )
            return

        await self.guardians.mark_running(row)
        try:
            context = await self._guardian_context(asset_row)
            image = ImageRef(
                data=await self.storage.get(asset_row.storage_key),
                mime_type=asset_row.mime_type,
            )
            result = await self.guardian.review(context, image)
        except AssetNotCheckable as exc:
            await self.guardians.mark_failed(
                row, error=_error(str(exc), code="ASSET_NOT_CHECKABLE")
            )
            return
        except StorageObjectNotFound:
            await self.guardians.mark_failed(
                row,
                error=_error(
                    "The generated image could not be read from storage.",
                    code="ASSET_UNREADABLE",
                ),
            )
            return
        except ProviderError as exc:
            log.warning("guardian_failed", result_id=str(result_id), code=exc.code)
            await self.guardians.mark_failed(row, error=_error(exc.message, code=exc.code))
            return
        except Exception as exc:  # noqa: BLE001 — a check must not die silently
            log.error("guardian_crashed", result_id=str(result_id), error=type(exc).__name__)
            await self.guardians.mark_failed(
                row,
                error=_error("The brand check failed unexpectedly. Try again.", code="INTERNAL"),
            )
            return

        await self.guardians.record_result(
            row,
            payload=result.model_dump(mode="json"),
            verdict=result.verdict.value,
            guardian_model=result.guardian_model,
        )

    # ----------------------------------------------------------- the revision
    async def revision_state(self, campaign_id: uuid.UUID) -> RevisionView:
        campaign = await self._campaign(campaign_id)
        history = await self.revisions.history(campaign.id)
        # The latest round, unless it was discarded. `open_revision` means
        # "waiting on a human" and guards against two proposals at once; the
        # view needs one step more than that, because immediately after Gate 2
        # the user still has to be told what they just approved and that
        # regeneration is now available.
        latest = await self.revisions.latest(campaign.id)
        current = (
            latest
            if latest is not None and latest.status != RevisionStatus.REJECTED.value
            else None
        )
        approved = await self._approved_specification(campaign.id)

        revised: CreativeSpecification | None = None
        source: CreativeSpecification | None = None
        if current is not None:
            source_row = await self.specifications.by_version(campaign.id, current.from_version)
            if source_row is not None:
                source = CreativeSpecification.model_validate(source_row.payload)
            if current.to_version is not None:
                revised_row = await self.specifications.by_version(campaign.id, current.to_version)
                if revised_row is not None:
                    revised = CreativeSpecification.model_validate(revised_row.payload)

        return RevisionView(
            campaign_id=str(campaign.id),
            current=current,
            history=history,
            revised_specification=revised,
            source_specification=source,
            can_revise=approved is not None,
            blocked_reason=(
                None
                if approved is not None
                else "Approve a Creative Specification before revising it."
            ),
        )

    async def propose_revision(
        self,
        campaign_id: uuid.UUID,
        *,
        feedback: str,
        source_asset_id: uuid.UUID | None = None,
    ) -> SpecificationRevisionRow:
        """Turn feedback into a delta and park it for review.

        Nothing is applied here. The delta is a proposal a human reads, edits
        and approves — which is the difference between a revision loop and an
        AI quietly rewriting approved work.
        """
        campaign = await self._campaign(campaign_id)
        if await self.revisions.open_revision(campaign.id) is not None:
            raise Conflict(
                "A revision is already open for this campaign. Approve or discard it first."
            )
        specification = await self._require_approved(campaign.id)

        asset_row: GeneratedAssetRow | None = None
        if source_asset_id is not None:
            asset_row = await self.assets.get(source_asset_id)
            if asset_row is None or asset_row.campaign_id != campaign.id:
                raise NotFound("Generated asset not found.")

        evaluation, guardian = await self._findings(asset_row)
        context = RevisionContext(
            specification=specification,
            feedback=feedback,
            iteration=await self.revisions.next_iteration(campaign.id),
            campaign=await self._campaign_specification(campaign.id),
            guardrails=(await self._creative_context(campaign)).guardrails,
            asset=_to_asset(asset_row) if asset_row is not None else None,
            evaluation_concerns=list(evaluation.concerns) if evaluation else [],
            guardian_fixes=guardian.fixes() if guardian else [],
        )

        try:
            delta = await self.planner.plan(context)
        except FeedbackTooVague as exc:
            # A question back to the human, not an error in the system.
            raise ValidationFailed(str(exc), details={"field": "feedback"}) from exc

        return await self.revisions.propose(
            campaign_id=campaign.id,
            iteration=context.iteration,
            user_feedback=feedback,
            delta=delta.model_dump(mode="json"),
            from_version=specification.version,
            source_asset_id=asset_row.id if asset_row is not None else None,
            evaluation_id=await self._evaluation_row_id(asset_row),
            guardian_id=await self._guardian_row_id(asset_row),
            requested_by=uuid.UUID(self.principal.user.id),
        )

    async def edit_delta(
        self, campaign_id: uuid.UUID, *, delta: RevisionDelta
    ) -> SpecificationRevisionRow:
        """Replace the proposal with the human's edited version.

        Re-validated, because an edit must not become the way around the rules
        the planner enforces.
        """
        campaign = await self._campaign(campaign_id)
        row = await self._open(campaign.id, expected=RevisionStatus.PROPOSED)
        validate_delta(delta)
        return await self.revisions.replace_delta(row, delta=delta.model_dump(mode="json"))

    async def approve_delta(self, campaign_id: uuid.UUID) -> SpecificationRevisionRow:
        """Gate 1. Apply the approved delta and store the next version.

        The application is a pure function, so what runs is exactly what the
        human just read.
        """
        campaign = await self._campaign(campaign_id)
        row = await self._open(campaign.id, expected=RevisionStatus.PROPOSED)
        delta = RevisionDelta.model_validate(row.delta)

        source_row = await self.specifications.by_version(campaign.id, row.from_version)
        if source_row is None:
            raise Conflict(f"Creative Specification v{row.from_version} is no longer available.")
        source = CreativeSpecification.model_validate(source_row.payload)

        revised, changed = apply_revision(source, delta)
        await self.specifications.upsert_version(
            campaign_id=campaign.id,
            version=revised.version,
            direction_id=uuid.UUID(revised.direction_id),
            payload=revised.model_dump(mode="json"),
        )
        log.info(
            "revision_version_created",
            campaign_id=str(campaign.id),
            from_version=source.version,
            to_version=revised.version,
            changed=changed,
        )
        return await self.revisions.mark_applied(
            row, to_version=revised.version, changed_fields=changed
        )

    async def approve_revised_specification(
        self, campaign_id: uuid.UUID
    ) -> SpecificationRevisionRow:
        """Gate 2. The revised version is approved and may be generated from."""
        campaign = await self._campaign(campaign_id)
        row = await self._open(campaign.id, expected=RevisionStatus.APPLIED)
        if row.to_version is None:
            raise Conflict("This revision has not been applied yet.")

        revised_row = await self.specifications.by_version(campaign.id, row.to_version)
        if revised_row is None:
            raise Conflict(f"Creative Specification v{row.to_version} is missing.")
        await self.specifications.approve(revised_row, user_id=uuid.UUID(self.principal.user.id))
        log.info(
            "revised_specification_approved",
            campaign_id=str(campaign.id),
            version=row.to_version,
        )
        return await self.revisions.mark_approved(row)

    async def reject_revision(self, campaign_id: uuid.UUID) -> SpecificationRevisionRow:
        """Discard the proposal. The specification never changed."""
        campaign = await self._campaign(campaign_id)
        row = await self.revisions.open_revision(campaign.id)
        if row is None:
            raise Conflict("There is no open revision to discard.")
        return await self.revisions.mark_rejected(row)

    # ------------------------------------------------------------- internals
    async def _open(
        self, campaign_id: uuid.UUID, *, expected: RevisionStatus
    ) -> SpecificationRevisionRow:
        row = await self.revisions.open_revision(campaign_id)
        if row is None:
            raise Conflict("There is no open revision.")
        if row.status != expected.value:
            raise Conflict(f"This revision is {row.status}, not {expected.value}.")
        return row

    async def _campaign(self, campaign_id: uuid.UUID) -> CampaignRow:
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    async def _assets(
        self, campaign: CampaignRow, asset_ids: list[uuid.UUID] | None
    ) -> list[GeneratedAssetRow]:
        rows = await self.assets.for_campaign(campaign.id)
        if asset_ids is None:
            return rows
        wanted = set(asset_ids)
        chosen = [row for row in rows if row.id in wanted]
        if len(chosen) != len(wanted):
            raise NotFound("Generated asset not found.")
        return chosen

    async def _approved_specification(self, campaign_id: uuid.UUID) -> CreativeSpecification | None:
        latest = await self.specifications.latest(campaign_id)
        if latest is None or latest.approved_at is None:
            return None
        return CreativeSpecification.model_validate(latest.payload)

    async def _require_approved(self, campaign_id: uuid.UUID) -> CreativeSpecification:
        specification = await self._approved_specification(campaign_id)
        if specification is None:
            raise Conflict("Approve a Creative Specification before revising it.")
        return specification

    async def _campaign_specification(self, campaign_id: uuid.UUID) -> CampaignBrief | None:
        row = await self.campaign_specifications.latest(campaign_id)
        return CampaignBrief.model_validate(row.payload) if row is not None else None

    async def _creative_context(self, campaign: CampaignRow) -> CreativeContext:
        from app.services.creative_context import CreativeContextService

        return await CreativeContextService(
            self.session,
            self.organization_id,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        ).build(campaign)

    async def _guardian_context(self, asset_row: GeneratedAssetRow) -> GuardianContext:
        """Assembled from scope-checked rows, against the asset's own plan."""
        specification_row = await self.specifications.by_version(
            asset_row.campaign_id, asset_row.specification_version
        )
        if specification_row is None:
            raise AssetNotCheckable(
                f"Creative Specification v{asset_row.specification_version} is no longer "
                "available, so this asset cannot be checked against its own plan."
            )
        campaign = await self._campaign(asset_row.campaign_id)
        context = await self._creative_context(campaign)
        evaluation, _ = await self._findings(asset_row)

        return GuardianContext(
            asset=_to_asset(asset_row),
            specification=CreativeSpecification.model_validate(specification_row.payload),
            campaign=await self._campaign_specification(asset_row.campaign_id),
            guardrails=context.guardrails,
            brand_name=context.brand_name,
            evaluation_concerns=list(evaluation.concerns) if evaluation else [],
        )

    async def _findings(
        self, asset_row: GeneratedAssetRow | None
    ) -> tuple[CreativeEvaluation | None, BrandGuardianResult | None]:
        """What the evaluator and guardian already said about this asset."""
        if asset_row is None:
            return None, None
        evaluation_row = await self.evaluations.for_asset(asset_row.id, EVALUATOR_VERSION)
        guardian_row = await self.guardians.for_asset(asset_row.id, GUARDIAN_VERSION)
        evaluation = (
            CreativeEvaluation.model_validate(evaluation_row.payload)
            if evaluation_row is not None and evaluation_row.payload
            else None
        )
        guardian = (
            BrandGuardianResult.model_validate(guardian_row.payload)
            if guardian_row is not None and guardian_row.payload
            else None
        )
        return evaluation, guardian

    async def _evaluation_row_id(self, asset_row: GeneratedAssetRow | None) -> uuid.UUID | None:
        if asset_row is None:
            return None
        row = await self.evaluations.for_asset(asset_row.id, EVALUATOR_VERSION)
        return row.id if row is not None and row.status == JobStatus.COMPLETED.value else None

    async def _guardian_row_id(self, asset_row: GeneratedAssetRow | None) -> uuid.UUID | None:
        if asset_row is None:
            return None
        row = await self.guardians.for_asset(asset_row.id, GUARDIAN_VERSION)
        return row.id if row is not None and row.status == JobStatus.COMPLETED.value else None


def _error(message: str, *, code: str) -> dict[str, object]:
    """A user-safe failure record. Never a traceback, never a vendor payload."""
    return ExecutionError(
        node="brand_guardian",
        severity=ErrorSeverity.ERROR,
        code=code,
        message=message,
    ).model_dump(mode="json")


async def run_guardian_in_background(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    result_ids: list[uuid.UUID],
) -> None:
    """Check concurrently, one session per check (ADR-012)."""

    async def _one(result_id: uuid.UUID) -> None:
        try:
            async with sessionmaker() as session:
                service = RevisionStageService(
                    session,
                    principal,
                    settings=settings,
                    storage=storage,
                    llm=llm,
                    embeddings=embeddings,
                )
                await service.run_guardian_check(result_id)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.error("guardian_task_crashed", result_id=str(result_id), error=type(exc).__name__)

    await asyncio.gather(*(_one(result_id) for result_id in result_ids))
