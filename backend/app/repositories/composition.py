"""Layout and final-asset persistence.

Same tenancy mechanism as everywhere else: `OrganizationOwnedRepository`
applies the organization filter, so no call site can forget it.

Both tables are append-only by version. A layout edit writes a new version; a
re-render writes a new final asset. Nothing here updates a historical row,
because an asset that has gone to a client has to stay exactly what it was.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.db.models import FinalAssetRow, LayoutSpecRow
from app.domain.common import Channel, utc_now
from app.repositories.base import OrganizationOwnedRepository


class LayoutSpecRepository(OrganizationOwnedRepository[LayoutSpecRow]):
    model = LayoutSpecRow

    async def latest(self, campaign_id: uuid.UUID, channel: Channel) -> LayoutSpecRow | None:
        stmt = (
            self.scoped()
            .where(
                LayoutSpecRow.campaign_id == campaign_id,
                LayoutSpecRow.channel == channel.value,
            )
            .order_by(LayoutSpecRow.version.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def by_version(
        self, campaign_id: uuid.UUID, channel: Channel, version: int
    ) -> LayoutSpecRow | None:
        """One exact version. A final asset points at the layout that rendered
        it, and "latest" would be the wrong answer after any edit."""
        stmt = self.scoped().where(
            LayoutSpecRow.campaign_id == campaign_id,
            LayoutSpecRow.channel == channel.value,
            LayoutSpecRow.version == version,
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def for_campaign(self, campaign_id: uuid.UUID) -> list[LayoutSpecRow]:
        """Every layout, every channel, oldest first."""
        stmt = (
            self.scoped()
            .where(LayoutSpecRow.campaign_id == campaign_id)
            .order_by(LayoutSpecRow.channel, LayoutSpecRow.version)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def channels(self, campaign_id: uuid.UUID) -> list[str]:
        """Which channels already have a composition."""
        stmt = self._scope(
            select(LayoutSpecRow.channel).distinct().select_from(LayoutSpecRow)
        ).where(LayoutSpecRow.campaign_id == campaign_id)
        return sorted((await self.session.execute(stmt)).scalars().all())

    async def next_version(self, campaign_id: uuid.UUID, channel: Channel) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(LayoutSpecRow.version), 0)).select_from(LayoutSpecRow)
        ).where(
            LayoutSpecRow.campaign_id == campaign_id,
            LayoutSpecRow.channel == channel.value,
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        channel: Channel,
        version: int,
        payload: dict[str, Any],
        source_asset_id: uuid.UUID | None,
        specification_version: int,
    ) -> LayoutSpecRow:
        row = LayoutSpecRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            channel=channel.value,
            version=version,
            payload=payload,
            source_asset_id=source_asset_id,
            specification_version=specification_version,
        )
        self.add(row)
        await self.session.flush()
        return row


class FinalAssetRepository(OrganizationOwnedRepository[FinalAssetRow]):
    model = FinalAssetRow

    async def for_campaign(self, campaign_id: uuid.UUID) -> list[FinalAssetRow]:
        """Newest first — the gallery shows the most recent render of each
        channel at the top, with its history beneath."""
        stmt = (
            self.scoped()
            .where(FinalAssetRow.campaign_id == campaign_id)
            .order_by(FinalAssetRow.created_at.desc(), FinalAssetRow.version.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def for_channel(self, campaign_id: uuid.UUID, channel: Channel) -> list[FinalAssetRow]:
        stmt = (
            self.scoped()
            .where(
                FinalAssetRow.campaign_id == campaign_id,
                FinalAssetRow.channel == channel.value,
            )
            .order_by(FinalAssetRow.version.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def next_version(self, campaign_id: uuid.UUID, channel: Channel) -> int:
        stmt = self._scope(
            select(func.coalesce(func.max(FinalAssetRow.version), 0)).select_from(FinalAssetRow)
        ).where(
            FinalAssetRow.campaign_id == campaign_id,
            FinalAssetRow.channel == channel.value,
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def create(
        self,
        *,
        campaign_id: uuid.UUID,
        channel: Channel,
        version: int,
        layout_spec_id: uuid.UUID | None,
        layout_version: int,
        layout_snapshot: dict[str, Any],
        source_asset_id: uuid.UUID | None,
        specification_version: int,
        renderer_version: str,
        storage_key: str,
        mime_type: str,
        width: int,
        height: int,
        size_bytes: int | None,
        rendered_by: uuid.UUID | None,
    ) -> FinalAssetRow:
        row = FinalAssetRow(
            organization_id=self.organization_id,
            campaign_id=campaign_id,
            channel=channel.value,
            version=version,
            layout_spec_id=layout_spec_id,
            layout_version=layout_version,
            layout_snapshot=layout_snapshot,
            source_asset_id=source_asset_id,
            specification_version=specification_version,
            renderer_version=renderer_version,
            storage_key=storage_key,
            mime_type=mime_type,
            width=width,
            height=height,
            bytes=size_bytes,
            rendered_by=rendered_by,
            # Stamped here, not by the server default: Postgres `now()` is
            # transaction-start time, so two renders in one transaction would
            # be indistinguishable by age and "newest first" would be a lie.
            created_at=utc_now(),
        )
        self.add(row)
        await self.session.flush()
        return row
