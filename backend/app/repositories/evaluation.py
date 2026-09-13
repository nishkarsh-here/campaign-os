"""Evaluation and selection persistence.

Same tenancy mechanism as everywhere else: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it. Every read is
scoped by organization *and* compared against a campaign resolved through its
own scoped repository — an evaluation id alone can never reach another tenant.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.db.models import CreativeEvaluationRow, CreativeSelectionRow
from app.domain.common import JobStatus, utc_now
from app.repositories.base import OrganizationOwnedRepository


class CreativeEvaluationRepository(OrganizationOwnedRepository[CreativeEvaluationRow]):
    model = CreativeEvaluationRow

    async def for_campaign(
        self, campaign_id: uuid.UUID, *, evaluator_version: str | None = None
    ) -> list[CreativeEvaluationRow]:
        """Every evaluation for a campaign, newest first.

        Filtered by evaluator version when given: comparing a `v1` result with
        a `v2` one as though they measured the same thing is exactly what the
        version exists to prevent.
        """
        stmt = self.scoped().where(CreativeEvaluationRow.campaign_id == campaign_id)
        if evaluator_version is not None:
            stmt = stmt.where(CreativeEvaluationRow.evaluator_version == evaluator_version)
        stmt = stmt.order_by(CreativeEvaluationRow.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_asset(
        self, asset_id: uuid.UUID, evaluator_version: str
    ) -> CreativeEvaluationRow | None:
        stmt = self.scoped().where(
            CreativeEvaluationRow.generated_asset_id == asset_id,
            CreativeEvaluationRow.evaluator_version == evaluator_version,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def claim(
        self,
        *,
        campaign_id: uuid.UUID,
        generated_asset_id: uuid.UUID,
        specification_id: uuid.UUID,
        specification_version: int,
        evaluator_version: str,
    ) -> CreativeEvaluationRow:
        """Create or reset the row for this asset and evaluator.

        Idempotent per `(asset, evaluator_version)`: starting evaluation twice
        reuses the row instead of creating a second opinion from the same
        criteria. A previous failure is cleared so a retry starts from a clean
        `PENDING` rather than carrying a stale error into a new attempt.
        """
        row = await self.for_asset(generated_asset_id, evaluator_version)
        if row is None:
            row = CreativeEvaluationRow(
                organization_id=self.organization_id,
                campaign_id=campaign_id,
                generated_asset_id=generated_asset_id,
                specification_id=specification_id,
                specification_version=specification_version,
                evaluator_version=evaluator_version,
                status=JobStatus.PENDING.value,
            )
            self.add(row)
        else:
            row.status = JobStatus.PENDING.value
            row.error = None
            row.started_at = None
            row.finished_at = None
        await self.session.flush()
        return row

    async def mark_running(self, row: CreativeEvaluationRow) -> CreativeEvaluationRow:
        row.status = JobStatus.RUNNING.value
        # Python-side rather than `func.now()`: a server default leaves the
        # attribute expired, and reading it back triggers a sync refresh inside
        # async context (the MissingGreenlet failure from Milestone 4).
        row.started_at = utc_now()
        await self.session.flush()
        return row

    async def record_result(
        self,
        row: CreativeEvaluationRow,
        *,
        payload: dict[str, Any],
        overall_score: float,
        disposition: str,
        evaluator_model: str | None,
    ) -> CreativeEvaluationRow:
        """Store the result. Score and disposition are written together with
        the payload they were computed from, never independently."""
        row.status = JobStatus.COMPLETED.value
        row.payload = payload
        row.overall_score = overall_score
        row.disposition = disposition
        row.evaluator_model = evaluator_model
        row.error = None
        row.finished_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(
        self, row: CreativeEvaluationRow, *, error: dict[str, Any]
    ) -> CreativeEvaluationRow:
        """`error` is a validated `ExecutionError` — a user-safe message and a
        code. A raw provider payload or a traceback must never reach here."""
        row.status = JobStatus.FAILED.value
        row.error = error
        row.payload = None
        row.overall_score = None
        row.disposition = None
        row.finished_at = utc_now()
        await self.session.flush()
        return row


class CreativeSelectionRepository(OrganizationOwnedRepository[CreativeSelectionRow]):
    model = CreativeSelectionRow

    async def current(self, campaign_id: uuid.UUID) -> CreativeSelectionRow | None:
        """The latest choice. The table is append-only, so this is the answer
        to "what is selected now?" and the rows behind it are the history."""
        stmt = (
            self.scoped()
            .where(CreativeSelectionRow.campaign_id == campaign_id)
            .order_by(CreativeSelectionRow.created_at.desc(), CreativeSelectionRow.id.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def history(self, campaign_id: uuid.UUID) -> list[CreativeSelectionRow]:
        stmt = (
            self.scoped()
            .where(CreativeSelectionRow.campaign_id == campaign_id)
            .order_by(CreativeSelectionRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def record(
        self,
        *,
        campaign_id: uuid.UUID,
        generated_asset_id: uuid.UUID,
        evaluation_id: uuid.UUID | None,
        selected_by: uuid.UUID | None,
        note: str | None = None,
    ) -> CreativeSelectionRow:
        row = CreativeSelectionRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            generated_asset_id=generated_asset_id,
            evaluation_id=evaluation_id,
            selected_by=selected_by,
            note=note,
        )
        self.add(row)
        await self.session.flush()
        return row
