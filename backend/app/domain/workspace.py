"""Organization / project / user — the tenancy spine.

Kept thin on purpose. Roles exist from day one so the architecture stays
compatible with real authorization, but nothing enforces fine-grained
permissions yet (PRODUCT_SPEC §4).
"""

from __future__ import annotations

from pydantic import Field

from app.domain.common import DomainModel, Id, Role


class Organization(DomainModel):
    id: Id
    name: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class User(DomainModel):
    id: Id
    email: str
    display_name: str | None = None


class Project(DomainModel):
    id: Id
    organization_id: Id
    name: str
    description: str | None = None


class Principal(DomainModel):
    """The resolved caller. Routes receive this, never a raw token."""

    user: User
    organization_id: Id
    role: Role = Role.MARKETING
