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
from app.domain.common import Role
from app.errors import AppError, Conflict, NotFound, ValidationFailed
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
        """Add a user to an organization.

        Four things can go wrong and they need four different answers. An
        earlier version mapped every `IntegrityError` to "already a member",
        which meant a rejected *role* was reported as a duplicate membership
        and sent the reader looking for a row that was never there.

        The role is checked before the insert rather than after, because a
        caller deserves the list of valid roles rather than a constraint name.
        The database check stays as the real guarantee, and the handler below
        still recognises it in case some other path reaches the table.
        """
        if role not in {member.value for member in Role}:
            raise ValidationFailed(
                f"{role!r} is not a role in this system.",
                details={"role": role, "allowed": [member.value for member in Role]},
            )

        membership = Membership(user_id=user_id, organization_id=organization_id, role=role)
        # A savepoint, so a rejected insert rolls back only this statement.
        # Without it the failure poisons the session and a caller that wanted
        # to handle the conflict could not continue.
        savepoint = await self.session.begin_nested()
        self.session.add(membership)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await savepoint.rollback()
            raise _membership_error(exc) from exc
        return membership


#: Constraint names on `memberships`, as PostgreSQL reports them. Matching on
#: the name rather than on the message text: messages are localised and get
#: reworded between server versions, names are part of the schema.
_MEMBERSHIP_DUPLICATE = "uq_memberships_organization_id_user_id"
_MEMBERSHIP_ROLE_CHECK = "role_valid"
_MEMBERSHIP_FOREIGN_KEYS = {
    "fk_memberships_user_id_users": "user",
    "fk_memberships_organization_id_organizations": "organization",
}


def _constraint_name(exc: IntegrityError) -> str:
    """The violated constraint, dug out of whatever the driver wrapped.

    asyncpg exposes it directly; other drivers do not, so this falls back to
    the rendered message rather than assuming a driver.
    """
    original = getattr(exc, "orig", None)
    for candidate in (original, getattr(original, "__cause__", None)):
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str) and name:
            return name
    return str(exc)


def _membership_error(exc: IntegrityError) -> AppError:
    """One integrity failure -> the error that actually describes it.

    Anything unrecognised is returned as a plain `AppError` carrying the
    constraint name, never as a duplicate-membership conflict. A wrong label
    is worse than a vague one: it is a confident answer to the wrong question.
    """
    name = _constraint_name(exc)

    if _MEMBERSHIP_DUPLICATE in name:
        return Conflict("That user is already a member of this organization.")
    if _MEMBERSHIP_ROLE_CHECK in name:
        return ValidationFailed(
            "That role is not one this system recognises.",
            details={"allowed": [member.value for member in Role]},
        )
    for constraint, subject in _MEMBERSHIP_FOREIGN_KEYS.items():
        if constraint in name:
            return NotFound(f"That {subject} does not exist.")
    return AppError(f"The membership could not be created: {name}")


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
