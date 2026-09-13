"""Row builders for integration tests.

Deliberately not a library: four helpers that make a test's setup readable.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Membership, Organization, Project, User


async def make_org(session: AsyncSession, slug: str | None = None) -> Organization:
    slug = slug or f"org-{uuid.uuid4().hex[:8]}"
    org = Organization(name=slug.replace("-", " ").title(), slug=slug)
    session.add(org)
    await session.flush()
    return org


async def make_user(session: AsyncSession, email: str | None = None) -> User:
    email = email or f"{uuid.uuid4().hex[:8]}@example.test"
    user = User(email=email, display_name="Test User", auth_subject=f"test:{email}")
    session.add(user)
    await session.flush()
    return user


async def make_membership(
    session: AsyncSession, user: User, org: Organization, role: str = "admin"
) -> Membership:
    membership = Membership(user_id=user.id, organization_id=org.id, role=role)
    session.add(membership)
    await session.flush()
    return membership


async def make_project(
    session: AsyncSession, org: Organization, name: str = "Test Project"
) -> Project:
    project = Project(organization_id=org.id, name=name)
    session.add(project)
    await session.flush()
    return project
