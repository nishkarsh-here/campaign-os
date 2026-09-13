"""Campaign persistence.

Same tenancy mechanism as every other repository: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it.

One rule specific to campaigns: `thread_id` is only ever read from a row these
repositories returned. Handing the checkpointer a campaign id straight from a
request would resume another tenant's execution, because the checkpointer has
no concept of an organization (M1_SECURITY_AUDIT A-5).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, select

from app.db.models import (
    CampaignMessageRow,
    CampaignReferenceRow,
    CampaignRow,
    CampaignRunRow,
    CampaignSpecificationRow,
)
from app.domain.common import utc_now
from app.repositories.base import OrganizationOwnedRepository


class CampaignRepository(OrganizationOwnedRepository[CampaignRow]):
    model = CampaignRow

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        return super()._scope(stmt).where(CampaignRow.deleted_at.is_(None))

    async def list_all(self, *, brand_id: uuid.UUID | None = None) -> list[CampaignRow]:
        stmt = self.scoped().order_by(CampaignRow.created_at.desc())
        if brand_id is not None:
            stmt = stmt.where(CampaignRow.brand_profile_id == brand_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        brand_id: uuid.UUID,
        title: str,
        project_id: uuid.UUID | None,
        created_by: uuid.UUID | None,
    ) -> CampaignRow:
        campaign_id = uuid.uuid4()
        row = CampaignRow(
            id=campaign_id,
            organization_id=self.organization_id,
            brand_profile_id=brand_id,
            project_id=project_id,
            title=title,
            status="DRAFT",
            # thread_id == campaign id: one campaign is one durable
            # conversation (ADR-003).
            thread_id=str(campaign_id),
            draft_inputs={},
            created_by=created_by,
        )
        self.add(row)
        await self.session.flush()
        return row

    async def set_status(self, row: CampaignRow, status: str) -> CampaignRow:
        row.status = status
        await self.session.flush()
        return row

    async def save_draft_inputs(self, row: CampaignRow, inputs: dict[str, Any]) -> CampaignRow:
        """Persist what the interview knows so far.

        Without this the running total lives only in the checkpoint, and the UI
        would have to read execution state to render it (ARCHITECTURE_REVIEW M-1).
        """
        row.draft_inputs = inputs
        await self.session.flush()
        return row

    async def soft_delete(self, row: CampaignRow) -> None:
        row.deleted_at = func.now()
        await self.session.flush()


class CampaignMessageRepository(OrganizationOwnedRepository[CampaignMessageRow]):
    model = CampaignMessageRow

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[CampaignMessageRow]:
        stmt = (
            self.scoped()
            .where(CampaignMessageRow.campaign_id == campaign_id)
            .order_by(CampaignMessageRow.sequence)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _next_sequence(self, campaign_id: uuid.UUID) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(CampaignMessageRow.sequence), -1)).select_from(
                CampaignMessageRow
            )
        ).where(CampaignMessageRow.campaign_id == campaign_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def append(
        self,
        *,
        campaign_id: uuid.UUID,
        role: str,
        content: str,
        targets_field: str | None = None,
        question_metadata: dict[str, Any] | None = None,
    ) -> CampaignMessageRow:
        row = CampaignMessageRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            sequence=await self._next_sequence(campaign_id),
            role=role,
            content=content,
            targets_field=targets_field,
            question_metadata=question_metadata or {},
        )
        self.add(row)
        await self.session.flush()
        return row


class CampaignRunRepository(OrganizationOwnedRepository[CampaignRunRow]):
    model = CampaignRunRow

    async def latest_for_campaign(self, campaign_id: uuid.UUID) -> CampaignRunRow | None:
        stmt = (
            self.scoped()
            .where(CampaignRunRow.campaign_id == campaign_id)
            .order_by(CampaignRunRow.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def start(self, campaign_id: uuid.UUID) -> CampaignRunRow:
        row = CampaignRunRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            status="RUNNING",
            started_at=func.now(),
            node_history=[],
        )
        self.add(row)
        await self.session.flush()
        return row

    async def finish(
        self,
        row: CampaignRunRow,
        *,
        status: str,
        current_node: str | None = None,
        error: str | None = None,
        node_history: list[Any] | None = None,
    ) -> CampaignRunRow:
        row.status = status
        row.current_node = current_node
        row.error = error
        if node_history is not None:
            row.node_history = node_history
        if status in {"COMPLETED", "FAILED", "CANCELLED"}:
            row.finished_at = func.now()
        await self.session.flush()
        return row


class CampaignSpecificationRepository(OrganizationOwnedRepository[CampaignSpecificationRow]):
    model = CampaignSpecificationRow

    async def latest(self, campaign_id: uuid.UUID) -> CampaignSpecificationRow | None:
        stmt = (
            self.scoped()
            .where(CampaignSpecificationRow.campaign_id == campaign_id)
            .order_by(CampaignSpecificationRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_version(self, campaign_id: uuid.UUID) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(CampaignSpecificationRow.version), 0)).select_from(
                CampaignSpecificationRow
            )
        ).where(CampaignSpecificationRow.campaign_id == campaign_id)
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def create_version(
        self, *, campaign_id: uuid.UUID, payload: dict[str, Any]
    ) -> CampaignSpecificationRow:
        """Every change is a new version. An edit never overwrites history, so
        "what did we agree to" stays answerable."""
        row = CampaignSpecificationRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            version=await self.next_version(campaign_id),
            payload=payload,
        )
        self.add(row)
        await self.session.flush()
        return row

    async def confirm(
        self, row: CampaignSpecificationRow, *, user_id: uuid.UUID | None
    ) -> CampaignSpecificationRow:
        row.confirmed_at = func.now()
        row.confirmed_by = user_id
        await self.session.flush()
        return row


class CampaignReferenceRepository(OrganizationOwnedRepository[CampaignReferenceRow]):
    model = CampaignReferenceRow

    async def list_for_campaign(self, campaign_id: uuid.UUID) -> list[CampaignReferenceRow]:
        stmt = (
            self.scoped()
            .where(CampaignReferenceRow.campaign_id == campaign_id)
            .order_by(CampaignReferenceRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        storage_key: str,
        filename: str | None,
        mime_type: str,
        size_bytes: int | None,
        note: str | None = None,
        content_sha256: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> CampaignReferenceRow:
        row = CampaignReferenceRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            storage_key=storage_key,
            filename=filename,
            mime_type=mime_type,
            bytes=size_bytes,
            note=note,
            content_sha256=content_sha256,
            width=width,
            height=height,
            status="PENDING",
        )
        self.add(row)
        await self.session.flush()
        return row

    async def find_analyzed_by_digest(
        self, campaign_id: uuid.UUID, digest: str
    ) -> CampaignReferenceRow | None:
        """An identical image already analysed for this campaign.

        Reusing it avoids paying for a second multimodal call on bytes we have
        already understood.
        """
        stmt = self.scoped().where(
            CampaignReferenceRow.campaign_id == campaign_id,
            CampaignReferenceRow.content_sha256 == digest,
            CampaignReferenceRow.status == "COMPLETED",
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def set_status(
        self,
        row: CampaignReferenceRow,
        status: str,
        *,
        analysis: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> CampaignReferenceRow:
        """The only way a reference's state changes.

        `error` is cleared on any non-failure transition, so a reference that
        succeeds on retry stops displaying its previous failure.
        """
        row.status = status
        row.error = error if status == "FAILED" else None
        if analysis is not None:
            row.analysis = analysis
            # A Python timestamp, not `func.now()`: a SQL expression leaves the
            # attribute expired after flush, and reading it back in async code
            # triggers a synchronous refresh (MissingGreenlet).
            row.analyzed_at = utc_now()
        await self.session.flush()
        return row

    async def accept(self, row: CampaignReferenceRow) -> CampaignReferenceRow:
        """A human has reviewed the analysis and agrees with it."""
        row.accepted_at = utc_now()
        await self.session.flush()
        return row
