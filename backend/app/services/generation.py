"""Generation orchestration.

Turns an *approved* Creative Specification into plates, through as many
providers as are configured.

**Generation is an explicit job, not a blocked request.** Starting a batch
compiles the prompts, writes one `PENDING` job per provider and returns
immediately; the providers are called afterwards, each job reaching its own
terminal status. The API never waits on an image model, and the frontend polls
the jobs. That is the same discipline documents and references already use —
Postgres rows carrying an explicit status — rather than a second orchestration
mechanism (ADR-012).

**Providers are independent.** One job per provider, run concurrently. A batch
where two of three succeeded produced two usable plates, and it is reported
that way rather than as a failure.

**Nothing starts from an unapproved plan.** The approved specification is the
entry condition, checked against the database rather than inferred from graph
state — an approval is a fact about a human, and it is stored as one.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import (
    CampaignRow,
    CanonicalPromptRow,
    GeneratedAssetRow,
    GenerationJobRow,
    ModelPromptRow,
)
from app.domain.common import ErrorSeverity, ExecutionError, JobStatus
from app.domain.creative import CreativeSpecification
from app.domain.generation import AssetKind, GeneratedAsset, GenerationBatch, GenerationJob
from app.domain.prompt import CanonicalPrompt, ModelPrompt
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound
from app.logging import get_logger
from app.providers.base import (
    EmbeddingProvider,
    ImageRequest,
    LLMProvider,
    ProviderError,
    ProviderUnavailable,
    StorageProvider,
)
from app.providers.registry import (
    ProviderNotConfigured,
    build_image_provider,
    build_prompt_adapter,
)
from app.repositories.campaigns import CampaignRepository
from app.repositories.creative import CreativeSpecificationRepository
from app.repositories.generation import (
    CanonicalPromptRepository,
    GeneratedAssetRepository,
    GenerationJobRepository,
    ModelPromptRepository,
)
from app.services.prompt_compiler import PromptCompiler

log = get_logger(__name__)


@dataclass(frozen=True)
class GenerationView:
    """Everything the generation screen needs, in one read."""

    campaign_id: str
    batch_id: str | None
    canonical_prompt: CanonicalPrompt | None
    prompts: list[ModelPrompt]
    batch: GenerationBatch | None
    specification_version: int | None
    can_generate: bool
    blocked_reason: str | None


class GenerationService:
    """Compiles prompts, starts jobs, and reads back what they produced."""

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
        self.specifications = CreativeSpecificationRepository(session, self.organization_id)
        self.canonical_prompts = CanonicalPromptRepository(session, self.organization_id)
        self.model_prompts = ModelPromptRepository(session, self.organization_id)
        self.jobs = GenerationJobRepository(session, self.organization_id)
        self.assets = GeneratedAssetRepository(session, self.organization_id)
        self.compiler = PromptCompiler()

    # ------------------------------------------------------------ reading
    async def current(self, campaign_id: uuid.UUID) -> GenerationView:
        campaign = await self._campaign(campaign_id)
        approved = await self._approved_specification(campaign.id)

        canonical_row = await self.canonical_prompts.latest(campaign.id)
        canonical = CanonicalPrompt.model_validate(canonical_row.payload) if canonical_row else None
        prompts = (
            [
                ModelPrompt.model_validate(row.payload)
                for row in await self.model_prompts.for_canonical(canonical_row.id)
            ]
            if canonical_row
            else []
        )

        batch_id = await self.jobs.latest_batch_id(campaign.id)
        batch = await self._batch(campaign.id, batch_id) if batch_id else None

        return GenerationView(
            campaign_id=str(campaign.id),
            batch_id=str(batch_id) if batch_id else None,
            canonical_prompt=canonical,
            prompts=prompts,
            batch=batch,
            specification_version=approved.version if approved else None,
            can_generate=approved is not None,
            blocked_reason=(
                None
                if approved is not None
                else "Approve the Creative Specification before generating."
            ),
        )

    async def compile_prompts(self, campaign_id: uuid.UUID) -> GenerationView:
        """Compile without generating.

        Separate from `start` so a user — and a reviewer — can see exactly what
        each provider will be asked, before any credit is spent.
        """
        campaign = await self._campaign(campaign_id)
        specification = await self._require_approved(campaign.id)
        await self._compile(campaign, specification)
        return await self.current(campaign_id)

    # ------------------------------------------------------------ starting
    async def start(self, campaign_id: uuid.UUID) -> tuple[GenerationView, uuid.UUID]:
        """Create one PENDING job per configured provider.

        Returns before any provider is called; the caller schedules
        `run_batch` and the frontend polls. Nothing here blocks on an image
        model.
        """
        campaign = await self._campaign(campaign_id)
        specification = await self._require_approved(campaign.id)
        canonical_row, prompt_rows = await self._compile(campaign, specification)

        batch_id = uuid.uuid4()
        for row in prompt_rows:
            prompt = ModelPrompt.model_validate(row.payload)
            key = _idempotency_key(canonical_row.id, prompt.provider, prompt.model, attempt=1)
            if await self.jobs.by_idempotency_key(key) is not None:
                # A replayed request. The existing job stands; charging a
                # provider twice for one click is the failure this prevents.
                continue
            await self.jobs.create(
                campaign_id=campaign.id,
                model_prompt_id=row.id,
                specification_id=uuid.UUID(specification.id),
                specification_version=specification.version,
                batch_id=batch_id,
                provider=prompt.provider,
                model=prompt.model,
                idempotency_key=key,
            )

        log.info(
            "generation_batch_started",
            campaign_id=str(campaign.id),
            batch_id=str(batch_id),
            providers=[ModelPrompt.model_validate(r.payload).provider for r in prompt_rows],
        )
        return await self.current(campaign_id), batch_id

    async def retry(self, campaign_id: uuid.UUID, job_id: uuid.UUID) -> uuid.UUID:
        """Re-run one failed job as a new attempt.

        A new attempt means a new idempotency key and therefore a new charge —
        which is what the user is asking for when they press Retry. A job that
        did not fail is not retried: re-running a success would pay twice for
        an image already in the gallery.
        """
        campaign = await self._campaign(campaign_id)
        row = await self.jobs.get(job_id)
        if row is None or row.campaign_id != campaign.id:
            raise NotFound("Generation job not found.")
        if row.status != JobStatus.FAILED.value:
            raise Conflict("Only a failed generation can be retried.")

        attempt = row.attempt + 1
        new_row = await self.jobs.create(
            campaign_id=campaign.id,
            model_prompt_id=row.model_prompt_id,
            specification_id=row.specification_id,
            specification_version=row.specification_version,
            batch_id=row.batch_id,
            provider=row.provider,
            model=row.model,
            idempotency_key=_idempotency_key(
                row.model_prompt_id, row.provider, row.model, attempt=attempt
            ),
            attempt=attempt,
        )
        return new_row.id

    # ----------------------------------------------------------- executing
    async def run_jobs(self, job_ids: list[uuid.UUID]) -> None:
        """Execute jobs one after another on this service's session.

        Sequential on purpose. An `AsyncSession` is not safe for concurrent
        use — gathering several jobs over one session raises "Session is
        already flushing" the moment two of them write at the same time.
        Providers still run independently in the sense that matters: each job
        reaches its own terminal status and one failure never stops another.

        Real concurrency lives in `run_batch_in_background`, which gives each
        job a session of its own.
        """
        for job_id in job_ids:
            await self.run_one(job_id)

    async def run_one(self, job_id: uuid.UUID) -> None:
        row = await self.jobs.get(job_id)
        if row is None or row.status != JobStatus.PENDING.value:
            return

        prompt_row = await self.model_prompts.get(row.model_prompt_id)
        if prompt_row is None:
            await self.jobs.mark_failed(
                row, error=_error("The compiled prompt is missing.", code="PROMPT_MISSING")
            )
            return

        prompt = ModelPrompt.model_validate(prompt_row.payload)
        await self.jobs.mark_running(row)

        try:
            try:
                provider = build_image_provider(self.settings, prompt.provider)
            except (ImportError, ProviderNotConfigured) as exc:
                # A provider named in configuration that this build has no
                # adapter for. "Not available" is the truth; the generic
                # "failed unexpectedly" below would send someone debugging.
                raise ProviderUnavailable(
                    f"{prompt.provider.title()} image generation is not available in this build.",
                    detail=str(exc),
                    provider=prompt.provider,
                ) from exc
            images = await provider.generate(
                ImageRequest(
                    prompt=prompt.text,
                    negative_prompt=prompt.negative_text,
                    aspect_ratio=prompt.aspect_ratio,
                    count=self.settings.generation_images_per_job,
                    parameters=prompt.parameters or None,
                    idempotency_key=row.idempotency_key,
                )
            )
        except ProviderError as exc:
            # A typed, user-safe failure. The vendor's own words stay in the
            # log, never in the row a browser will read.
            log.warning(
                "generation_failed",
                job_id=str(job_id),
                provider=prompt.provider,
                code=exc.code,
                detail=exc.detail,
            )
            await self.jobs.mark_failed(row, error=_error(exc.message, code=exc.code))
            return
        except Exception as exc:  # noqa: BLE001 — a job must never die silently
            log.error(
                "generation_crashed",
                job_id=str(job_id),
                provider=prompt.provider,
                error=type(exc).__name__,
            )
            await self.jobs.mark_failed(
                row,
                error=_error("Generation failed unexpectedly. Try again.", code="INTERNAL"),
            )
            return

        if not images:
            await self.jobs.mark_failed(
                row,
                error=_error("The provider returned no image.", code="PROVIDER_INVALID_RESPONSE"),
            )
            return

        for image in images:
            key = generated_asset_key(
                organization_id=self.organization_id,
                campaign_id=row.campaign_id,
                job_id=row.id,
                mime_type=image.mime_type,
            )
            await self.storage.put(key, image.data, mime_type=image.mime_type)
            await self.assets.create(
                campaign_id=row.campaign_id,
                generation_job_id=row.id,
                model_prompt_id=row.model_prompt_id,
                specification_id=row.specification_id,
                specification_version=row.specification_version,
                provider=row.provider,
                model=row.model,
                # What this actually is: a plate, not a finished creative.
                kind=AssetKind.VISUAL_PLATE.value,
                storage_key=key,
                mime_type=image.mime_type,
                width=image.width,
                height=image.height,
                size_bytes=len(image.data),
                seed=image.seed,
                metadata=dict(image.metadata or {}),
            )

        await self.jobs.mark_completed(row, provider_job_id=images[0].provider_job_id)
        log.info("generation_completed", job_id=str(job_id), provider=prompt.provider)

    # ------------------------------------------------------------ internals
    async def _campaign(self, campaign_id: uuid.UUID) -> CampaignRow:
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    async def _approved_specification(self, campaign_id: uuid.UUID) -> CreativeSpecification | None:
        """The approved plan, or None.

        Approval is read from the database rather than inferred from graph
        state: it is a fact about a human, and it is stored as one.
        """
        latest = await self.specifications.latest(campaign_id)
        if latest is None or latest.approved_at is None:
            return None
        return CreativeSpecification.model_validate(latest.payload)

    async def _require_approved(self, campaign_id: uuid.UUID) -> CreativeSpecification:
        """The entry condition for every generation path."""
        specification = await self._approved_specification(campaign_id)
        if specification is None:
            raise Conflict(
                "Generation needs an approved Creative Specification. Approve the plan first."
            )
        return specification

    async def _compile(
        self, campaign: CampaignRow, specification: CreativeSpecification
    ) -> tuple[CanonicalPromptRow, list[ModelPromptRow]]:
        """Compile the canonical prompt and one model prompt per provider.

        An unchanged specification reuses its existing canonical prompt rather
        than adding an identical version: compilation is deterministic, so a
        new version number would say a change happened when none did.
        """
        from app.services.creative_context import CreativeContextService

        context = await CreativeContextService(
            self.session,
            self.organization_id,
            storage=self.storage,
            llm=self.llm,
            embeddings=self.embeddings,
        ).build(campaign)

        draft = self.compiler.compile(specification, context=context)
        existing = await self.canonical_prompts.find_by_fingerprint(
            campaign.id, draft.source_fingerprint
        )
        if existing is not None:
            canonical_row = existing
            canonical = CanonicalPrompt.model_validate(existing.payload)
        else:
            version = await self.canonical_prompts.next_version(campaign.id)
            canonical = self.compiler.compile(specification, context=context, version=version)
            canonical_row = await self.canonical_prompts.create(
                campaign_id=campaign.id,
                specification_id=uuid.UUID(specification.id),
                specification_version=specification.version,
                version=version,
                payload=canonical.model_dump(mode="json"),
                source_fingerprint=canonical.source_fingerprint,
            )

        prompt_rows = []
        for provider_name in self.settings.image_provider_list:
            adapter = build_prompt_adapter(self.settings, provider_name)
            prompt = adapter.compile(canonical, version=canonical.version)
            prompt_rows.append(
                await self.model_prompts.upsert(
                    campaign_id=campaign.id,
                    canonical_prompt_id=canonical_row.id,
                    provider=prompt.provider,
                    model=prompt.model,
                    version=prompt.version,
                    payload=prompt.model_dump(mode="json"),
                )
            )
        return canonical_row, prompt_rows

    async def _batch(self, campaign_id: uuid.UUID, batch_id: uuid.UUID) -> GenerationBatch | None:
        rows = await self.jobs.for_batch(batch_id)
        if not rows:
            return None
        jobs = [_to_job(row) for row in rows]
        asset_rows = await self.assets.for_jobs([row.id for row in rows])
        return GenerationBatch(
            id=str(batch_id),
            campaign_id=str(campaign_id),
            specification_id=str(rows[0].specification_id),
            specification_version=rows[0].specification_version,
            jobs=jobs,
            assets=[_to_asset(row) for row in asset_rows],
        )


def generated_asset_key(
    *,
    organization_id: uuid.UUID,
    campaign_id: uuid.UUID,
    job_id: uuid.UUID,
    mime_type: str,
) -> str:
    """The storage key for a generated plate.

    Entirely generated: no part of it comes from anything a user typed, so a
    filename can never traverse a path or collide with another tenant's object.
    The organization prefix is defence in depth — access control stays in the
    scoped repositories — and makes a mis-scoped read obvious in logs.
    """
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
        mime_type, "bin"
    )
    return (
        f"org-{organization_id}/campaign-{campaign_id}/generated/"
        f"{job_id}-{uuid.uuid4().hex}.{extension}"
    )


def _idempotency_key(prompt_id: uuid.UUID, provider: str, model: str, *, attempt: int) -> str:
    """Same prompt, provider, model and attempt -> same key -> one charge.

    `attempt` is deliberately part of it: a replayed request must not charge
    twice, but a deliberate retry must be allowed to.
    """
    return f"{prompt_id}:{provider}:{model}:{attempt}"


def _error(message: str, *, code: str) -> dict[str, object]:
    """A user-safe failure record. Never a traceback, never a vendor payload."""
    return ExecutionError(
        node="image_generation",
        severity=ErrorSeverity.ERROR,
        code=code,
        message=message,
    ).model_dump(mode="json")


def _to_job(row: GenerationJobRow) -> GenerationJob:
    return GenerationJob(
        id=str(row.id),
        campaign_id=str(row.campaign_id),
        prompt_id=str(row.model_prompt_id),
        specification_id=str(row.specification_id),
        specification_version=row.specification_version,
        provider=row.provider,
        model=row.model,
        status=JobStatus(row.status),
        batch_id=str(row.batch_id),
        idempotency_key=row.idempotency_key,
        attempt=row.attempt,
        provider_job_id=row.provider_job_id,
        error=ExecutionError.model_validate(row.error) if row.error else None,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )


def _to_asset(row: GeneratedAssetRow) -> GeneratedAsset:
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


async def run_batch_in_background(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    principal: Principal,
    settings: Settings,
    storage: StorageProvider,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    job_ids: list[uuid.UUID],
) -> None:
    """Execute a batch on its own session.

    The request's session is closed by the time this runs, so it opens its own
    and commits it. Failures are already recorded on the job rows by
    `run_jobs`; anything that escapes is logged rather than vanishing into a
    task nobody awaits.
    """

    async def _one(job_id: uuid.UUID) -> None:
        # A session per job, because these run concurrently and an
        # `AsyncSession` is not safe to share between concurrent tasks.
        try:
            async with sessionmaker() as session:
                service = GenerationService(
                    session,
                    principal,
                    settings=settings,
                    storage=storage,
                    llm=llm,
                    embeddings=embeddings,
                )
                await service.run_one(job_id)
                await session.commit()
        except Exception as exc:  # noqa: BLE001 — a task nobody awaits must not
            # swallow its failure. The job row already carries the user-facing
            # error for every handled case; this covers the rest.
            log.error("generation_job_crashed", job_id=str(job_id), error=type(exc).__name__)

    # Providers run independently: one slow or failing provider never holds up
    # another, and the batch ends with as many plates as the working ones made.
    await asyncio.gather(*(_one(job_id) for job_id in job_ids))
