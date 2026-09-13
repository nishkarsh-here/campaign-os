"""Projects."""

from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_

from app.db.models import Project
from app.errors import ValidationFailed
from app.repositories.base import OrganizationOwnedRepository


@dataclass(frozen=True)
class Page:
    items: list[Project]
    next_cursor: str | None


def _encode_cursor(project: Project) -> str:
    raw = f"{project.created_at.isoformat()}|{project.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Returns a real `datetime`, not the string it was encoded as.

    Postgres will not compare `timestamptz > varchar`, so handing the raw
    string straight into the WHERE clause fails at the second page — which is
    exactly where nobody looks.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at, _, entity_id = raw.partition("|")
        return datetime.fromisoformat(created_at), uuid.UUID(entity_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailed("Invalid cursor.", details={"cursor": cursor}) from exc


class ProjectRepository(OrganizationOwnedRepository[Project]):
    model = Project

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        """Scope to the organization *and* hide soft-deleted rows.

        Soft deletion is part of scope, not a caller's responsibility: a
        deleted project must not reappear because one query forgot the filter.
        """
        return super()._scope(stmt).where(Project.deleted_at.is_(None))

    async def list_page(self, *, limit: int = 50, cursor: str | None = None) -> Page:
        """Keyset pagination on (created_at, id) — stable under inserts, which
        offset pagination is not (API_SPEC §Lists)."""
        limit = max(1, min(limit, 100))
        stmt = self.scoped().order_by(Project.created_at, Project.id)
        if cursor:
            created_at, entity_id = _decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Project.created_at > created_at,
                    and_(Project.created_at == created_at, Project.id > entity_id),
                )
            )
        rows = list((await self.session.execute(stmt.limit(limit + 1))).scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        return Page(items=items, next_cursor=_encode_cursor(items[-1]) if has_more else None)

    async def create(
        self, *, name: str, description: str | None, created_by: uuid.UUID | None
    ) -> Project:
        project = Project(
            organization_id=self.organization_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        self.add(project)
        await self.session.flush()
        return project

    async def soft_delete(self, project: Project) -> None:
        from sqlalchemy import func

        project.deleted_at = func.now()
        await self.session.flush()
