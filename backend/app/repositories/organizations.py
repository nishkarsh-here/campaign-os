"""Organizations and memberships.

`organizations` is the one table that cannot be scoped by `organization_id` —
it *is* the organization. It is scoped by membership instead: a caller may
only see organizations they belong to. Same guarantee, different join.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Membership, Organization, User
from app.errors import Conflict
from app.repositories.base import ScopedRepository


class OrganizationRepository(ScopedRepository[Organization]):
    model = Organization

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        return stmt.where(Organization.id == self.organization_id)

    def _assert_owned(self, entity: Organization) -> None:
        # An organization has no organization_id; the base check does not apply.
        return None

    async def current(self) -> Organization | None:
        return await self.get(self.organization_id)


class MembershipRepository:
    """Not organization-scoped: it answers "which organizations may this user
    see?", which is the question that *establishes* scope. Every method is
    therefore keyed on a user id and can never leak across users.
    """

    def __init__(self, session: Any) -> None:
        self.session = session

    async def organizations_for_user(self, user_id: uuid.UUID) -> list[tuple[Organization, str]]:
        stmt = (
            select(Organization, Membership.role)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.name)
        )
        return [(org, role) for org, role in (await self.session.execute(stmt)).all()]

    async def role_in(self, user_id: uuid.UUID, organization_id: uuid.UUID) -> str | None:
        stmt = select(Membership.role).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id
        )
        role: str | None = (await self.session.execute(stmt)).scalars().one_or_none()
        return role

    async def grant(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID, role: str
    ) -> Membership:
        membership = Membership(user_id=user_id, organization_id=organization_id, role=role)
        self.session.add(membership)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise Conflict("That user is already a member of this organization.") from exc
        return membership


class UserRepository:
    """Users are global, not organization-scoped — one person can belong to
    several organizations. Scope is applied by membership, above.
    """

    def __init__(self, session: Any) -> None:
        self.session = session

    async def by_subject(self, subject: str) -> User | None:
        stmt = select(User).where(User.auth_subject == subject)
        user: User | None = (await self.session.execute(stmt)).scalars().one_or_none()
        return user

    async def by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        user: User | None = (await self.session.execute(stmt)).scalars().one_or_none()
        return user

    async def get(self, user_id: uuid.UUID) -> User | None:
        user: User | None = await self.session.get(User, user_id)
        return user

    async def upsert_from_identity(
        self, *, subject: str, email: str, display_name: str | None
    ) -> User:
        """Provision on first sight, keyed on the identity-provider subject.

        **Identity is the subject, never the email.** An earlier version fell
        back to `by_email()` when the subject was unknown, which meant any
        provider that asserted a victim's email address — verified or not —
        was handed the victim's existing account, with all of its memberships.
        The dev stub asserts one fixed identity so it was not reachable, but
        this is exactly the seam a real IdP plugs into, so the hole would have
        shipped with the provider swap.

        Email is a profile attribute. It is unique in the schema, so an email
        already bound to a different subject is a conflict to surface, not a
        link to make silently.
        """
        existing = await self.by_subject(subject)
        if existing is not None:
            if display_name and not existing.display_name:
                existing.display_name = display_name
            await self.session.flush()
            return existing

        user = User(auth_subject=subject, email=email, display_name=display_name)
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "That email address is already registered to a different sign-in method."
            ) from exc
        return user


async def create_organization(session: Any, *, name: str, slug: str) -> Organization:
    """Creating an organization is not a scoped operation — there is no scope
    yet. It lives as a function rather than on the scoped repository so the
    distinction cannot be blurred.
    """
    organization = Organization(name=name, slug=slug)
    session.add(organization)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise Conflict(f"An organization with slug {slug!r} already exists.") from exc
    return organization
