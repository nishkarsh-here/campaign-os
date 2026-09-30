"""Projects."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select

from app.db.models import Project
from app.repositories.base import OrganizationOwnedRepository
from app.repositories.pagination import DEFAULT_LIMIT, Page, keyset_page


class ProjectRepository(OrganizationOwnedRepository[Project]):
    model = Project

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        """Scope to the organization *and* hide soft-deleted rows.

        Soft deletion is part of scope, not a caller's responsibility: a
        deleted project must not reappear because one query forgot the filter.
        """
        return super()._scope(stmt).where(Project.deleted_at.is_(None))

    async def list_page(
        self, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None
    ) -> Page[Project]:
        """Keyset pagination on (created_at, id) — stable under inserts, which
        offset pagination is not (API_SPEC §Lists). The mechanism itself lives in
        `app/repositories/pagination.py`, shared with brands and campaigns."""
        return await keyset_page(self.session, self.scoped(), Project, limit=limit, cursor=cursor)

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
