"""Prompt and generation persistence.

Same tenancy mechanism as everywhere else: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it. Every read here
therefore scopes by organization *and* by the campaign resolved through its own
scoped repository — a job id alone can never reach another tenant's row.

Prompts are versioned rather than mutated. Recompiling adds a row, so the exact
text a provider was charged for stays on record next to the asset it produced.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.models import (
    CanonicalPromptRow,
    GeneratedAssetRow,
    GenerationJobRow,
    ModelPromptRow,
)
from app.domain.common import JobStatus, utc_now
from app.repositories.base import OrganizationOwnedRepository


class CanonicalPromptRepository(OrganizationOwnedRepository[CanonicalPromptRow]):
    model = CanonicalPromptRow

    async def latest(self, campaign_id: uuid.UUID) -> CanonicalPromptRow | None:
        stmt = (
            self.scoped()
            .where(CanonicalPromptRow.campaign_id == campaign_id)
            .order_by(CanonicalPromptRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_version(self, campaign_id: uuid.UUID) -> int:
        latest = await self.latest(campaign_id)
        return 1 if latest is None else latest.version + 1

    async def find_by_fingerprint(
        self, campaign_id: uuid.UUID, fingerprint: str
    ) -> CanonicalPromptRow | None:
        """An identical compile of an unchanged specification.

        Compilation is deterministic, so recompiling an unchanged plan would
        add a row identical to one already stored. Reusing it keeps the version
        history meaningful — a new version means something actually changed.
        """
        stmt = (
            self.scoped()
            .where(
                CanonicalPromptRow.campaign_id == campaign_id,
                CanonicalPromptRow.source_fingerprint == fingerprint,
            )
            .order_by(CanonicalPromptRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        specification_id: uuid.UUID,
        specification_version: int,
        version: int,
        payload: dict[str, Any],
        source_fingerprint: str,
    ) -> CanonicalPromptRow:
        row = CanonicalPromptRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            specification_id=specification_id,
            specification_version=specification_version,
            version=version,
            payload=payload,
            source_fingerprint=source_fingerprint,
        )
        self.add(row)
        await self.session.flush()
        return row


class ModelPromptRepository(OrganizationOwnedRepository[ModelPromptRow]):
    model = ModelPromptRow

    async def for_canonical(self, canonical_prompt_id: uuid.UUID) -> list[ModelPromptRow]:
        stmt = (
            self.scoped()
            .where(ModelPromptRow.canonical_prompt_id == canonical_prompt_id)
            .order_by(ModelPromptRow.provider, ModelPromptRow.version)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_campaign(self, campaign_id: uuid.UUID) -> list[ModelPromptRow]:
        stmt = (
            self.scoped()
            .where(ModelPromptRow.campaign_id == campaign_id)
            .order_by(ModelPromptRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        campaign_id: uuid.UUID,
        canonical_prompt_id: uuid.UUID,
        provider: str,
        model: str,
        version: int,
        payload: dict[str, Any],
    ) -> ModelPromptRow:
        """Idempotent per (canonical prompt, provider, model, version).

        Recompiling the same canonical prompt for the same provider is a
        no-op rather than a duplicate row — the canonical prompt is what
        versions, and a provider's rendering of it is a pure function.
        """
        stmt = self.scoped().where(
            ModelPromptRow.canonical_prompt_id == canonical_prompt_id,
            ModelPromptRow.provider == provider,
            ModelPromptRow.model == model,
            ModelPromptRow.version == version,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            row = ModelPromptRow(
                organization_id=self.organization_id,
                campaign_id=campaign_id,
                canonical_prompt_id=canonical_prompt_id,
                provider=provider,
                model=model,
                version=version,
                payload=payload,
            )
            self.add(row)
        else:
            row.payload = payload
        await self.session.flush()
        return row


class GenerationJobRepository(OrganizationOwnedRepository[GenerationJobRow]):
    model = GenerationJobRow

    async def for_campaign(self, campaign_id: uuid.UUID) -> list[GenerationJobRow]:
        stmt = (
            self.scoped()
            .where(GenerationJobRow.campaign_id == campaign_id)
            .order_by(GenerationJobRow.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_batch(self, batch_id: uuid.UUID) -> list[GenerationJobRow]:
        stmt = (
            self.scoped()
            .where(GenerationJobRow.batch_id == batch_id)
            .order_by(GenerationJobRow.provider)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_batch_id(self, campaign_id: uuid.UUID) -> uuid.UUID | None:
        """The batch of the most recently created job.

        Ordering rests on `created_at` being stamped Python-side in `create`:
        Postgres' `now()` is *transaction-start* time, so two batches begun in
        one transaction would share a timestamp exactly and this would pick
        between them arbitrarily. The same trap as `campaign_messages.sequence`
        in Milestone 3.
        """
        stmt = (
            self.scoped()
            .where(GenerationJobRow.campaign_id == campaign_id)
            .order_by(GenerationJobRow.created_at.desc())
        )
        row = (await self.session.execute(stmt)).scalars().first()
        return None if row is None else row.batch_id

    async def by_idempotency_key(self, key: str) -> GenerationJobRow | None:
        """The replay guard. A repeated request finds its existing job here
        instead of charging a provider twice."""
        stmt = self.scoped().where(GenerationJobRow.idempotency_key == key)
        return (await self.session.execute(stmt)).scalars().first()

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        model_prompt_id: uuid.UUID,
        specification_id: uuid.UUID,
        specification_version: int,
        batch_id: uuid.UUID,
        provider: str,
        model: str,
        idempotency_key: str,
        attempt: int = 1,
    ) -> GenerationJobRow:
        row = GenerationJobRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            model_prompt_id=model_prompt_id,
            specification_id=specification_id,
            specification_version=specification_version,
            batch_id=batch_id,
            provider=provider,
            model=model,
            status=JobStatus.PENDING.value,
            idempotency_key=idempotency_key,
            attempt=attempt,
            # Stamped here, not by the server default: `now()` is
            # transaction-start time in Postgres, so jobs created in one
            # transaction would be indistinguishable by age.
            created_at=utc_now(),
        )
        self.add(row)
        await self.session.flush()
        return row

    async def mark_running(self, row: GenerationJobRow) -> GenerationJobRow:
        row.status = JobStatus.RUNNING.value
        # Python-side rather than `func.now()`: a server default leaves the
        # attribute expired, and reading it back triggers a sync refresh inside
        # async context (the MissingGreenlet failure from Milestone 4).
        row.started_at = utc_now()
        await self.session.flush()
        return row

    async def mark_completed(
        self, row: GenerationJobRow, *, provider_job_id: str | None = None
    ) -> GenerationJobRow:
        row.status = JobStatus.COMPLETED.value
        row.provider_job_id = provider_job_id
        row.error = None
        row.finished_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(
        self, row: GenerationJobRow, *, error: dict[str, Any]
    ) -> GenerationJobRow:
        """`error` is a validated `ExecutionError` — a user-safe message and a
        code. A raw provider payload or a traceback must never reach here."""
        row.status = JobStatus.FAILED.value
        row.error = error
        row.finished_at = utc_now()
        await self.session.flush()
        return row


class GeneratedAssetRepository(OrganizationOwnedRepository[GeneratedAssetRow]):
    model = GeneratedAssetRow

    async def for_campaign(self, campaign_id: uuid.UUID) -> list[GeneratedAssetRow]:
        stmt = (
            self.scoped()
            .where(GeneratedAssetRow.campaign_id == campaign_id)
            .order_by(GeneratedAssetRow.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_jobs(self, job_ids: list[uuid.UUID]) -> list[GeneratedAssetRow]:
        if not job_ids:
            return []
        stmt = (
            self.scoped()
            .where(GeneratedAssetRow.generation_job_id.in_(job_ids))
            .order_by(GeneratedAssetRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        generation_job_id: uuid.UUID,
        model_prompt_id: uuid.UUID,
        specification_id: uuid.UUID,
        specification_version: int,
        provider: str,
        model: str,
        kind: str,
        storage_key: str,
        mime_type: str,
        width: int,
        height: int,
        size_bytes: int | None = None,
        seed: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GeneratedAssetRow:
        row = GeneratedAssetRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            generation_job_id=generation_job_id,
            model_prompt_id=model_prompt_id,
            specification_id=specification_id,
            specification_version=specification_version,
            provider=provider,
            model=model,
            kind=kind,
            storage_key=storage_key,
            mime_type=mime_type,
            width=width,
            height=height,
            bytes=size_bytes,
            seed=seed,
            meta=metadata or {},
        )
        self.add(row)
        await self.session.flush()
        return row
