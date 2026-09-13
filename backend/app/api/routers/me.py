"""The caller's identity and workspaces."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUserDep, SessionDep
from app.api.schemas import MeResponse, OrganizationMembership
from app.domain.common import Role
from app.domain.workspace import Organization
from app.repositories.organizations import MembershipRepository

router = APIRouter(prefix="/me", tags=["me"])


@router.get("", response_model=MeResponse)
async def get_me(user: CurrentUserDep, session: SessionDep) -> MeResponse:
    """Deliberately does not require a resolved organization: the shell calls
    this *to discover* which organizations exist for the switcher."""
    owned = await MembershipRepository(session).organizations_for_user(uuid.UUID(user.id))
    memberships = [
        OrganizationMembership(
            organization=Organization(id=str(org.id), name=org.name, slug=org.slug),
            role=Role(role),
        )
        for org, role in owned
    ]
    return MeResponse(
        user=user,
        organizations=memberships,
        active_organization_id=memberships[0].organization.id if len(memberships) == 1 else None,
    )
