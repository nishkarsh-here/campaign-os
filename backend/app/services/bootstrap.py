"""Development workspace bootstrap.

The dev auth stub asserts an identity but knows nothing about our database —
that separation is the point (see `app/auth/base.py`). Something still has to
make sure that identity has an organization to work in, so it happens here, at
startup, and only when the stub is selected.

Keeping it out of the request path means the authenticated-request flow is
byte-for-byte identical in development and production.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import AuthenticatedUser
from app.config import Settings
from app.db.models import Organization, User
from app.domain.common import Role
from app.logging import get_logger
from app.repositories.organizations import (
    MembershipRepository,
    UserRepository,
    create_organization,
)

log = get_logger(__name__)


async def ensure_dev_workspace(
    session: AsyncSession, settings: Settings
) -> tuple[User, Organization]:
    """Idempotently create the demo user, organization and membership."""
    users = UserRepository(session)
    identity = AuthenticatedUser(
        subject=f"dev-stub:{settings.dev_stub_user_email}",
        email=settings.dev_stub_user_email,
        display_name="Demo User",
    )
    user = await users.upsert_from_identity(
        subject=identity.subject, email=identity.email, display_name=identity.display_name
    )

    from sqlalchemy import select

    slug = settings.dev_stub_org_slug
    organization = (
        await session.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if organization is None:
        organization = await create_organization(
            session, name=slug.replace("-", " ").title(), slug=slug
        )
        log.info("dev_workspace_created", slug=slug)

    memberships = MembershipRepository(session)
    if await memberships.role_in(user.id, organization.id) is None:
        await memberships.grant(
            user_id=user.id, organization_id=organization.id, role=Role.ADMIN.value
        )
    await session.commit()
    return user, organization
