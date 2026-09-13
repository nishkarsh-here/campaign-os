"""Brand Guardian and specification-revision persistence.

Same tenancy mechanism as everywhere else: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it, and every read
is compared against a campaign resolved through its own scoped repository.

Revision history is append-only. A row is never deleted and `from_version`
never moves, so "what did this look like before, and why did it change?" stays
answerable for as long as the campaign does.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.db.models import BrandGuardianResultRow, SpecificationRevisionRow
from app.domain.common import JobStatus, utc_now
from app.domain.revision import RevisionStatus
from app.repositories.base import OrganizationOwnedRepository


class BrandGuardianRepository(OrganizationOwnedRepository[BrandGuardianResultRow]):
    model = BrandGuardianResultRow

    async def for_campaign(
        self, campaign_id: uuid.UUID, *, guardian_version: str | None = None
    ) -> list[BrandGuardianResultRow]:
        stmt = self.scoped().where(BrandGuardianResultRow.campaign_id == campaign_id)
        if guardian_version is not None:
            stmt = stmt.where(BrandGuardianResultRow.guardian_version == guardian_version)
        stmt = stmt.order_by(BrandGuardianResultRow.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_asset(
        self, asset_id: uuid.UUID, guardian_version: str
    ) -> BrandGuardianResultRow | None:
        stmt = self.scoped().where(
            BrandGuardianResultRow.generated_asset_id == asset_id,
            BrandGuardianResultRow.guardian_version == guardian_version,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def claim(
        self,
        *,
        campaign_id: uuid.UUID,
        generated_asset_id: uuid.UUID,
        specification_id: uuid.UUID,
        specification_version: int,
        guardian_version: str,
    ) -> BrandGuardianResultRow:
        """Create or reset the row for this asset and guardian version.

        Idempotent per `(asset, guardian_version)`: re-checking resets the row
        rather than adding a second opinion from identical rules. A previous
        failure is cleared so a retry starts clean.
        """
        row = await self.for_asset(generated_asset_id, guardian_version)
        if row is None:
            row = BrandGuardianResultRow(
                organization_id=self.organization_id,
                campaign_id=campaign_id,
                generated_asset_id=generated_asset_id,
                specification_id=specification_id,
                specification_version=specification_version,
                guardian_version=guardian_version,
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

    async def mark_running(self, row: BrandGuardianResultRow) -> BrandGuardianResultRow:
        row.status = JobStatus.RUNNING.value
        # Python-side rather than `func.now()`: a server default leaves the
        # attribute expired, and reading it back triggers a sync refresh inside
        # async context (the MissingGreenlet failure from Milestone 4).
        row.started_at = utc_now()
        await self.session.flush()
        return row

    async def record_result(
        self,
        row: BrandGuardianResultRow,
        *,
        payload: dict[str, Any],
        verdict: str,
        guardian_model: str | None,
    ) -> BrandGuardianResultRow:
        row.status = JobStatus.COMPLETED.value
        row.payload = payload
        row.verdict = verdict
        row.guardian_model = guardian_model
        row.error = None
        row.finished_at = utc_now()
        await self.session.flush()
        return row

    async def mark_failed(
        self, row: BrandGuardianResultRow, *, error: dict[str, Any]
    ) -> BrandGuardianResultRow:
        """A check that could not run. The verdict stays null rather than
        becoming a pass — an outage must never read as brand approval."""
        row.status = JobStatus.FAILED.value
        row.error = error
        row.payload = None
        row.verdict = None
        row.finished_at = utc_now()
        await self.session.flush()
        return row


class SpecificationRevisionRepository(OrganizationOwnedRepository[SpecificationRevisionRow]):
    model = SpecificationRevisionRow

    async def history(self, campaign_id: uuid.UUID) -> list[SpecificationRevisionRow]:
        """Every round, oldest first. Append-only, so this is the whole story."""
        stmt = (
            self.scoped()
            .where(SpecificationRevisionRow.campaign_id == campaign_id)
            .order_by(SpecificationRevisionRow.iteration)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest(self, campaign_id: uuid.UUID) -> SpecificationRevisionRow | None:
        stmt = (
            self.scoped()
            .where(SpecificationRevisionRow.campaign_id == campaign_id)
            .order_by(SpecificationRevisionRow.iteration.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def open_revision(self, campaign_id: uuid.UUID) -> SpecificationRevisionRow | None:
        """The round waiting on a human, if there is one.

        Only one revision may be in flight per campaign: two open proposals
        against the same specification would race to become the next version.
        """
        stmt = (
            self.scoped()
            .where(
                SpecificationRevisionRow.campaign_id == campaign_id,
                SpecificationRevisionRow.status.in_(
                    (RevisionStatus.PROPOSED.value, RevisionStatus.APPLIED.value)
                ),
            )
            .order_by(SpecificationRevisionRow.iteration.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_iteration(self, campaign_id: uuid.UUID) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(SpecificationRevisionRow.iteration), 0)).select_from(
                SpecificationRevisionRow
            )
        ).where(SpecificationRevisionRow.campaign_id == campaign_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def propose(
        self,
        *,
        campaign_id: uuid.UUID,
        iteration: int,
        user_feedback: str,
        delta: dict[str, Any],
        from_version: int,
        source_asset_id: uuid.UUID | None = None,
        evaluation_id: uuid.UUID | None = None,
        guardian_id: uuid.UUID | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> SpecificationRevisionRow:
        row = SpecificationRevisionRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            iteration=iteration,
            status=RevisionStatus.PROPOSED.value,
            user_feedback=user_feedback,
            delta=delta,
            changed_fields=[],
            from_version=from_version,
            source_asset_id=source_asset_id,
            evaluation_id=evaluation_id,
            guardian_id=guardian_id,
            requested_by=requested_by,
        )
        self.add(row)
        await self.session.flush()
        return row

    async def replace_delta(
        self, row: SpecificationRevisionRow, *, delta: dict[str, Any]
    ) -> SpecificationRevisionRow:
        """A human edited the proposal before approving it.

        Overwrites the proposal in place rather than adding a row: what matters
        historically is the delta that was *approved*, and an unapproved draft
        is not yet part of the campaign's history.
        """
        row.delta = delta
        await self.session.flush()
        return row

    async def mark_applied(
        self,
        row: SpecificationRevisionRow,
        *,
        to_version: int,
        changed_fields: list[str],
    ) -> SpecificationRevisionRow:
        row.status = RevisionStatus.APPLIED.value
        row.to_version = to_version
        row.changed_fields = changed_fields
        await self.session.flush()
        return row

    async def mark_approved(self, row: SpecificationRevisionRow) -> SpecificationRevisionRow:
        row.status = RevisionStatus.APPROVED.value
        await self.session.flush()
        return row

    async def mark_rejected(self, row: SpecificationRevisionRow) -> SpecificationRevisionRow:
        """The human threw the proposal away. The specification never changed,
        and the row stays as a record that the question was asked."""
        row.status = RevisionStatus.REJECTED.value
        await self.session.flush()
        return row
