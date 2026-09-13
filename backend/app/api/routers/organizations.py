"""Organizations."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUserDep, PrincipalDep, SessionDep
from app.api.schemas import CreateOrganizationRequest
from app.domain.common import Role
from app.domain.workspace import Organization
from app.errors import NotFound
from app.repositories.organizations import (
    MembershipRepository,
    OrganizationRepository,
    create_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=Organization, status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateOrganizationRequest, user: CurrentUserDep, session: SessionDep
) -> Organization:
    """Creating an organization needs no organization scope — it establishes
    one. The creator becomes its admin."""
    row = await create_organization(session, name=body.name, slug=body.slug)
    await MembershipRepository(session).grant(
        user_id=uuid.UUID(user.id), organization_id=row.id, role=Role.ADMIN.value
    )
    return Organization(id=str(row.id), name=row.name, slug=row.slug)


@router.get("/current", response_model=Organization)
async def current(principal: PrincipalDep, session: SessionDep) -> Organization:
    repo = OrganizationRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.current()
    if row is None:
        raise NotFound("Organization not found.")
    return Organization(id=str(row.id), name=row.name, slug=row.slug)
