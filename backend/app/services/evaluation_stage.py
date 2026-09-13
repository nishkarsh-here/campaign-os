"""Evaluation orchestration.

Runs the Creative Evaluator over the plates a campaign has generated, ranks
what came back, and records the human's final choice.

**Every asset is judged independently.** One evaluation per asset, each
reaching its own terminal status. Seven successes and one failure is seven
usable evaluations and a named failure — never a batch thrown away.

**Each asset is judged against its own plan.** The specification is looked up
by the version the *asset* was generated from, not by whatever is latest. An
evaluation against a plan the asset never saw would be meaningless, and after a
Milestone 5 revision that is exactly what "latest" would mean.

**Evaluation assesses; it never creates.** Nothing here writes to a Creative
Specification, a prompt or an asset. The only things it writes are evaluations
and the human's selection.

**Concurrency comes with its own session**, exactly as generation does
(ADR-012): `run_evaluations_in_background` opens one session per evaluation,
because an `AsyncSession` shared between gathered tasks raises "Session is
already flushing" the moment two of them write.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import CampaignRow, CreativeEvaluationRow, GeneratedAssetRow
from app.domain.campaign import CampaignBrief
from app.domain.common import ErrorSeverity, ExecutionError, JobStatus
from app.domain.creative import CreativeSpecification
from app.domain.evaluation import EVALUATOR_VERSION, CreativeEvaluation, EvaluationSummary
from app.domain.generation import GeneratedAsset
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound
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
from app.repositories.evaluation import (
    CreativeEvaluationRepository,
    CreativeSelectionRepository,
)
from app.repositories.generation import GeneratedAssetRepository
from app.services.creative_evaluator import (
    AssetNotEvaluable,
    CreativeEvaluator,
    EvaluationContext,
)
from app.services.recommendation import summarise

log = get_logger(__name__)


@dataclass(frozen=True)
class EvaluationView:
    """Everything the recommendation screen needs, in one read."""

    campaign_id: str
    summary: EvaluationSummary
    #: Assets with no evaluation row yet — what "Evaluate" would work on.
    unevaluated_asset_ids: list[str]
    #: Evaluations still PENDING or RUNNING; the UI polls while any remain.
    in_flight: int
    can_evaluate: bool
    blocked_reason: str | None


class EvaluationService:
    """Claims evaluations, runs them, ranks them, records the choice."""

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
        self.selections = CreativeSelectionRepository(session, self.organization_id)
        self.evaluator = CreativeEvaluator(llm)

    # ------------------------------------------------------------ reading
    async def current(self, campaign_id: uuid.UUID) -> EvaluationView:
        campaign = await self._campaign(campaign_id)
        asset_rows = await self.assets.for_campaign(campaign.id)
        rows = await self.evaluations.for_campaign(campaign.id, evaluator_version=EVALUATOR_VERSION)

        completed = [
            CreativeEvaluation.model_validate(row.payload)
            for row in rows
            if row.status == JobStatus.COMPLETED.value and row.payload
        ]
        failed = [
            str(row.generated_asset_id) for row in rows if row.status == JobStatus.FAILED.value
        ]
        in_flight = sum(
            1 for row in rows if row.status in (JobStatus.PENDING.value, JobStatus.RUNNING.value)
        )
        evaluated_ids = {str(row.generated_asset_id) for row in rows}

        selection = await self.selections.current(campaign.id)
        summary = summarise(
            str(campaign.id),
            completed,
            failed_asset_ids=failed,
            selected_asset_id=str(selection.generated_asset_id) if selection else None,
            evaluator_version=EVALUATOR_VERSION,
        )

        return EvaluationView(
            campaign_id=str(campaign.id),
            summary=summary,
            unevaluated_asset_ids=[
                str(row.id) for row in asset_rows if str(row.id) not in evaluated_ids
            ],
            in_flight=in_flight,
            can_evaluate=bool(asset_rows),
            blocked_reason=(None if asset_rows else "Generate creatives before evaluating them."),
        )

    # ------------------------------------------------------------ starting
    async def start(
        self, campaign_id: uuid.UUID, *, asset_ids: list[uuid.UUID] | None = None
    ) -> tuple[EvaluationView, list[uuid.UUID]]:
        """Claim a PENDING evaluation for each asset and return immediately.

        The model is not called here; the caller schedules the work and the
        frontend polls. Re-claiming an asset already evaluated by this
        evaluator version resets that row rather than adding a second opinion
        from identical criteria.
        """
        campaign = await self._campaign(campaign_id)
        rows = await self._assets_to_evaluate(campaign, asset_ids)
        if not rows:
            raise Conflict("There are no generated creatives to evaluate.")

        claimed: list[uuid.UUID] = []
        for asset in rows:
            row = await self.evaluations.claim(
                campaign_id=campaign.id,
                generated_asset_id=asset.id,
                specification_id=asset.specification_id,
                specification_version=asset.specification_version,
                evaluator_version=EVALUATOR_VERSION,
            )
            claimed.append(row.id)

        log.info(
            "evaluation_batch_started",
            campaign_id=str(campaign.id),
            assets=len(claimed),
            evaluator_version=EVALUATOR_VERSION,
        )
        return await self.current(campaign_id), claimed

    async def retry(self, campaign_id: uuid.UUID, evaluation_id: uuid.UUID) -> uuid.UUID:
        """Re-run one failed evaluation.

        Only a failure is retried: re-running a success would spend a model
        call to replace a result that is already there.
        """
        campaign = await self._campaign(campaign_id)
        row = await self.evaluations.get(evaluation_id)
        if row is None or row.campaign_id != campaign.id:
            raise NotFound("Evaluation not found.")
        if row.status != JobStatus.FAILED.value:
            raise Conflict("Only a failed evaluation can be retried.")

        await self.evaluations.claim(
            campaign_id=campaign.id,
            generated_asset_id=row.generated_asset_id,
            specification_id=row.specification_id,
            specification_version=row.specification_version,
            evaluator_version=EVALUATOR_VERSION,
        )
        return row.id

    # ----------------------------------------------------------- executing
    async def run_evaluations(self, evaluation_ids: list[uuid.UUID]) -> None:
        """Run several on this service's session, one after another.

        Sequential on purpose — see `run_evaluations_in_background` for the
        concurrent path, which gives each evaluation a session of its own.
        """
        for evaluation_id in evaluation_ids:
            await self.run_one(evaluation_id)

    async def run_one(self, evaluation_id: uuid.UUID) -> None:
        """Evaluate one asset, recording success or a user-safe failure.

        Never raises: a failed evaluation is a row, not an exception, which is
        what keeps the rest of the batch usable.
        """
        row = await self.evaluations.get(evaluation_id)
        if row is None or row.status != JobStatus.PENDING.value:
            return

        asset_row = await self.assets.get(row.generated_asset_id)
        if asset_row is None:
            await self.evaluations.mark_failed(
                row, error=_error("The generated asset is missing.", code="ASSET_MISSING")
            )
            return

        await self.evaluations.mark_running(row)

        try:
            context = await self._context(asset_row)
            image = ImageRef(
                data=await self.storage.get(asset_row.storage_key),
                mime_type=asset_row.mime_type,
            )
            evaluation = await self.evaluator.evaluate(context, image)
        except AssetNotEvaluable as exc:
            # A deterministic pre-check, not a provider problem. Recorded with
            # the same explicitness so the UI can explain it.
            await self.evaluations.mark_failed(
                row, error=_error(str(exc), code="ASSET_NOT_EVALUABLE")
            )
            return
        except StorageObjectNotFound:
            # The row survived but its bytes did not. Its own code, because
            # "storage lost the file" and "the model refused" need different
            # answers from whoever reads this.
            await self.evaluations.mark_failed(
                row,
                error=_error(
                    "The generated image could not be read from storage.",
                    code="ASSET_UNREADABLE",
                ),
            )
            return
        except ProviderError as exc:
            log.warning(
                "evaluation_failed",
                evaluation_id=str(evaluation_id),
                code=exc.code,
                detail=exc.detail,
            )
            await self.evaluations.mark_failed(row, error=_error(exc.message, code=exc.code))
            return
        except Exception as exc:  # noqa: BLE001 — an evaluation must not die silently
            log.error(
                "evaluation_crashed",
                evaluation_id=str(evaluation_id),
                error=type(exc).__name__,
            )
            await self.evaluations.mark_failed(
                row, error=_error("Evaluation failed unexpectedly. Try again.", code="INTERNAL")
            )
            return

        await self.evaluations.record_result(
            row,
            payload=evaluation.model_dump(mode="json"),
            overall_score=evaluation.overall_score,
            disposition=evaluation.disposition.value,
            evaluator_model=evaluation.evaluator_model,
        )

    # ----------------------------------------------------------- selecting
    async def select(
        self, campaign_id: uuid.UUID, asset_id: uuid.UUID, *, note: str | None = None
    ) -> EvaluationView:
        """Record the human's final choice.

        Any asset in the campaign may be chosen, evaluated or not: the ranking
        is advice, and a person who disagrees with it is still the decision
        maker. The evaluation is recorded alongside when one exists, so a later
        milestone can say what was known at the time.
        """
        campaign = await self._campaign(campaign_id)
        asset = await self.assets.get(asset_id)
        if asset is None or asset.campaign_id != campaign.id:
            raise NotFound("Generated asset not found.")

        evaluation = await self.evaluations.for_asset(asset.id, EVALUATOR_VERSION)
        await self.selections.record(
            campaign_id=campaign.id,
            generated_asset_id=asset.id,
            evaluation_id=(
                evaluation.id
                if evaluation is not None and evaluation.status == JobStatus.COMPLETED.value
                else None
            ),
            selected_by=uuid.UUID(self.principal.user.id),
            note=note,
        )
        log.info("creative_selected", campaign_id=str(campaign.id), asset_id=str(asset.id))
        return await self.current(campaign_id)

    # ------------------------------------------------------------ internals
    async def _campaign(self, campaign_id: uuid.UUID) -> CampaignRow:
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    async def _assets_to_evaluate(
        self, campaign: CampaignRow, asset_ids: list[uuid.UUID] | None
    ) -> list[GeneratedAssetRow]:
        rows = await self.assets.for_campaign(campaign.id)
        if asset_ids is None:
            return rows
        # Filtered against the campaign's own assets, so an id from elsewhere
        # simply is not there rather than being looked up separately.
        wanted = set(asset_ids)
        chosen = [row for row in rows if row.id in wanted]
        if len(chosen) != len(wanted):
            raise NotFound("Generated asset not found.")
        return chosen

    async def _context(self, asset_row: GeneratedAssetRow) -> EvaluationContext:
        """Assemble what the evaluator needs, from scope-checked rows only."""
        specification_row = await self.specifications.by_version(
            asset_row.campaign_id, asset_row.specification_version
        )
        if specification_row is None:
            raise AssetNotEvaluable(
                f"Creative Specification v{asset_row.specification_version} is no longer "
                "available, so this asset cannot be judged against its own plan."
            )

        campaign_specification: CampaignBrief | None = None
        latest = await self.campaign_specifications.latest(asset_row.campaign_id)
        if latest is not None:
            campaign_specification = CampaignBrief.model_validate(latest.payload)

        from app.services.creative_context import CreativeContextService

        campaign = await self._campaign(asset_row.campaign_id)
        creative_context = await CreativeContextService(
            self.session,
            self.organization_id,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        ).build(campaign)

        return EvaluationContext(
            asset=_to_asset(asset_row),
            specification=CreativeSpecification.model_validate(specification_row.payload),
            campaign=campaign_specification,
            guardrails=creative_context.guardrails,
            reference_style=creative_context.reference_style,
            brand_name=creative_context.brand_name,
        )


def _error(message: str, *, code: str) -> dict[str, object]:
    """A user-safe failure record. Never a traceback, never a vendor payload."""
    return ExecutionError(
        node="creative_evaluator",
        severity=ErrorSeverity.ERROR,
        code=code,
        message=message,
    ).model_dump(mode="json")


def _to_asset(row: GeneratedAssetRow) -> GeneratedAsset:
    from app.domain.generation import AssetKind

    return GeneratedAsset(
        id=str(row.id),
        campaign_id=str(row.campaign_id),
        generation_job_id=str(row.generation_job_id),
        prompt_id=str(row.model_prompt_id),
        specification_id=str(row.specification_id),
        specification_version=row.specification_version,
        provider=row.provider,
        model=row.model,
        kind=AssetKind(row.kind),
        storage_key=row.storage_key,
        mime_type=row.mime_type,
        width=row.width,
        height=row.height,
        seed=row.seed,
        created_at=row.created_at,
        metadata=dict(row.meta or {}),
    )


def evaluation_row_status(row: CreativeEvaluationRow) -> JobStatus:
    return JobStatus(row.status)


async def run_evaluations_in_background(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    evaluation_ids: list[uuid.UUID],
) -> None:
    """Evaluate concurrently, one session per evaluation.

    The request's session is closed by the time this runs, and an
    `AsyncSession` cannot be shared between concurrent tasks — so each gets its
    own and commits it. One asset's failure never stops another's: every
    handled failure is already a row, and this only catches what escapes.
    """

    async def _one(evaluation_id: uuid.UUID) -> None:
        try:
            async with sessionmaker() as session:
                service = EvaluationService(
                    session,
                    principal,
                    settings=settings,
                    storage=storage,
                    llm=llm,
                    embeddings=embeddings,
                )
                await service.run_one(evaluation_id)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            log.error(
                "evaluation_task_crashed",
                evaluation_id=str(evaluation_id),
                error=type(exc).__name__,
            )

    await asyncio.gather(*(_one(evaluation_id) for evaluation_id in evaluation_ids))
