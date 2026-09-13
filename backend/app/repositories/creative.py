"""Creative stage persistence.

Same tenancy mechanism as everywhere else: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it.

Direction sets and specifications are versioned rather than mutated —
a revision adds a version, so "what did we reject, and why" stays answerable.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.db.models import (
    CreativeApprovalRow,
    CreativeDirectionSetRow,
    CreativeRevisionRow,
    CreativeSpecificationRow,
)
from app.domain.common import utc_now
from app.repositories.base import OrganizationOwnedRepository


class CreativeDirectionSetRepository(OrganizationOwnedRepository[CreativeDirectionSetRow]):
    model = CreativeDirectionSetRow

    async def latest(self, campaign_id: uuid.UUID) -> CreativeDirectionSetRow | None:
        stmt = (
            self.scoped()
            .where(CreativeDirectionSetRow.campaign_id == campaign_id)
            .order_by(CreativeDirectionSetRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_versions(self, campaign_id: uuid.UUID) -> list[CreativeDirectionSetRow]:
        stmt = (
            self.scoped()
            .where(CreativeDirectionSetRow.campaign_id == campaign_id)
            .order_by(CreativeDirectionSetRow.version)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert_version(
        self,
        *,
        campaign_id: uuid.UUID,
        version: int,
        payload: dict[str, Any],
        selected_direction_id: uuid.UUID | None = None,
    ) -> CreativeDirectionSetRow:
        """Idempotent per version: re-projecting the same graph state must not
        create duplicate rows."""
        stmt = self.scoped().where(
            CreativeDirectionSetRow.campaign_id == campaign_id,
            CreativeDirectionSetRow.version == version,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            row = CreativeDirectionSetRow(
                organization_id=self.organization_id,
                campaign_id=campaign_id,
                version=version,
                payload=payload,
            )
            self.add(row)
        else:
            row.payload = payload
        if selected_direction_id is not None:
            row.selected_direction_id = selected_direction_id
            row.approved_at = row.approved_at or utc_now()
        await self.session.flush()
        return row


class CreativeSpecificationRepository(OrganizationOwnedRepository[CreativeSpecificationRow]):
    model = CreativeSpecificationRow

    async def latest(self, campaign_id: uuid.UUID) -> CreativeSpecificationRow | None:
        stmt = (
            self.scoped()
            .where(CreativeSpecificationRow.campaign_id == campaign_id)
            .order_by(CreativeSpecificationRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def by_version(
        self, campaign_id: uuid.UUID, version: int
    ) -> CreativeSpecificationRow | None:
        """One exact version.

        An asset is always judged against the plan it was *generated* from, so
        evaluation looks a version up rather than taking whatever is latest —
        marking work against a plan it never saw would be meaningless.
        """
        stmt = self.scoped().where(
            CreativeSpecificationRow.campaign_id == campaign_id,
            CreativeSpecificationRow.version == version,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def upsert_version(
        self,
        *,
        campaign_id: uuid.UUID,
        version: int,
        direction_id: uuid.UUID | None,
        payload: dict[str, Any],
    ) -> CreativeSpecificationRow:
        stmt = self.scoped().where(
            CreativeSpecificationRow.campaign_id == campaign_id,
            CreativeSpecificationRow.version == version,
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            row = CreativeSpecificationRow(
                organization_id=self.organization_id,
                campaign_id=campaign_id,
                version=version,
                direction_id=direction_id,
                payload=payload,
            )
            self.add(row)
        else:
            row.payload = payload
        await self.session.flush()
        return row

    async def approve(
        self, row: CreativeSpecificationRow, *, user_id: uuid.UUID | None
    ) -> CreativeSpecificationRow:
        row.approved_at = utc_now()
        row.approved_by = user_id
        await self.session.flush()
        return row


class CreativeApprovalRepository(OrganizationOwnedRepository[CreativeApprovalRow]):
    """Append-only. A decision is never edited or removed."""

    model = CreativeApprovalRow

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[CreativeApprovalRow]:
        stmt = (
            self.scoped()
            .where(CreativeApprovalRow.campaign_id == campaign_id)
            .order_by(CreativeApprovalRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def record(
        self,
        *,
        campaign_id: uuid.UUID,
        gate: str,
        decision: str,
        target_id: uuid.UUID | None,
        feedback: str | None,
        decided_by: uuid.UUID | None,
    ) -> CreativeApprovalRow:
        row = CreativeApprovalRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            gate=gate,
            decision=decision,
            target_id=target_id,
            feedback=feedback,
            decided_by=decided_by,
        )
        self.add(row)
        await self.session.flush()
        return row


class CreativeRevisionRepository(OrganizationOwnedRepository[CreativeRevisionRow]):
    model = CreativeRevisionRow

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[CreativeRevisionRow]:
        stmt = (
            self.scoped()
            .where(CreativeRevisionRow.campaign_id == campaign_id)
            .order_by(CreativeRevisionRow.iteration)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_iteration(self, campaign_id: uuid.UUID) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(CreativeRevisionRow.iteration), 0)).select_from(
                CreativeRevisionRow
            )
        ).where(CreativeRevisionRow.campaign_id == campaign_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def record(
        self,
        *,
        campaign_id: uuid.UUID,
        iteration: int,
        delta: dict[str, Any],
        from_version: int | None = None,
        to_version: int | None = None,
    ) -> CreativeRevisionRow:
        """Idempotent per iteration: re-projecting must not duplicate history."""
        stmt = self.scoped().where(
            CreativeRevisionRow.campaign_id == campaign_id,
            CreativeRevisionRow.iteration == iteration,
        )
        existing: CreativeRevisionRow | None = (await self.session.execute(stmt)).scalars().first()
        if existing is not None:
            return existing
        row = CreativeRevisionRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            iteration=iteration,
            delta=delta,
            from_version=from_version,
            to_version=to_version,
        )
        self.add(row)
        await self.session.flush()
        return row
