"""The organization-scoping mechanism.

`docs/DATABASE_SCHEMA.md` records a deliberate decision: root tables carry
`organization_id`, descendants are reached by joining to their campaign or
project. That decision is only safe if the scope is applied in exactly one
place, automatically, on every query — otherwise it is 23 chances to forget.

This base class is that place. A repository declares *how* it is scoped by
implementing `_scope()`; every read and write then goes through `scoped()`. A
subclass that forgets is caught by `tests/integration/test_org_isolation.py`,
which runs the same cross-tenant probe against every registered repository.

Cross-organization access returns *nothing* — never a permission error. The
route turns that into 404, so a caller cannot learn that a resource exists
(API_SPEC §Scope).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Entity


class ScopedRepository[ModelT: Entity](ABC):
    """Base for every repository. Scope is not optional."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        self.session = session
        self.organization_id = organization_id

    @abstractmethod
    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        """Narrow a statement to this organization.

        Direct descendants of `organizations` filter on their own
        `organization_id`; deeper tables (from Milestone 3) join up to the
        table that has one. Implementing this is the whole contract.
        """

    def scoped(self) -> Select[Any]:
        return self._scope(select(self.model))

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """None for 'does not exist' *and* for 'belongs to another
        organization' — the caller cannot tell the difference, by design."""
        stmt = self.scoped().where(self.model.id == entity_id)
        row: ModelT | None = (await self.session.execute(stmt)).scalars().one_or_none()
        return row

    async def count(self) -> int:
        stmt = self._scope(select(func.count()).select_from(self.model))
        return int((await self.session.execute(stmt)).scalar_one())

    def add(self, entity: ModelT) -> ModelT:
        """Stage an insert. Subclasses must set the scoping column themselves —
        `_assert_owned` verifies it before the flush."""
        self._assert_owned(entity)
        self.session.add(entity)
        return entity

    def _assert_owned(self, entity: ModelT) -> None:
        """Guard against writing a row into another organization.

        Only meaningful for tables with their own `organization_id`; deeper
        tables override this with their own parent check.
        """
        owner = getattr(entity, "organization_id", None)
        if owner is not None and owner != self.organization_id:
            raise PermissionError(
                f"{type(entity).__name__} belongs to organization {owner}, "
                f"not {self.organization_id}"
            )


class OrganizationOwnedRepository[ModelT: Entity](ScopedRepository[ModelT]):
    """For tables that carry `organization_id` directly."""

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        return stmt.where(self.model.organization_id == self.organization_id)  # type: ignore[attr-defined]
