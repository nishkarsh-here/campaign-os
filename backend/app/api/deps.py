"""Dependency injection.

Resolving a `Principal` is two separate steps on purpose:

1. **Who are you?** — the `AuthProvider` answers, from the credential alone.
2. **Which organization, and may you?** — resolved here from the request and
   checked against `memberships`.

Splitting them is what makes the auth provider replaceable: swapping the dev
stub for a real IdP changes step 1 only, and step 2 — the part that actually
guards data — is identical in every environment.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.base import AuthenticationError, AuthProvider
from app.auth.registry import get_auth_provider
from app.config import Settings, get_settings
from app.db.session import session_scope
from app.domain.common import Role
from app.domain.workspace import Principal, User
from app.errors import Forbidden, NotFound, Unauthenticated
from app.providers.base import EmbeddingProvider, LLMProvider, StorageProvider
from app.providers.registry import (
    build_embedding_provider,
    build_llm_provider,
    build_storage_provider,
)
from app.repositories.organizations import MembershipRepository, UserRepository

ORGANIZATION_HEADER = "X-Organization-Id"


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in session_scope():
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_db)]
AuthDep = Annotated[AuthProvider, Depends(get_auth_provider)]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token or None if scheme.lower() == "bearer" else None


async def get_current_user(request: Request, session: SessionDep, auth: AuthDep) -> User:
    try:
        identity = await auth.authenticate(_bearer(request))
    except AuthenticationError as exc:
        raise Unauthenticated("Sign in to continue.", detail=str(exc)) from exc

    row = await UserRepository(session).upsert_from_identity(
        subject=identity.subject, email=identity.email, display_name=identity.display_name
    )
    return User(id=str(row.id), email=row.email, display_name=row.display_name)


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_principal(
    session: SessionDep,
    user: CurrentUserDep,
    x_organization_id: Annotated[str | None, Header(alias=ORGANIZATION_HEADER)] = None,
) -> Principal:
    """Resolve the organization this request acts in, and prove membership.

    With no header, a caller who belongs to exactly one organization gets it
    implicitly — convenient, and unambiguous. A caller in several must say
    which, rather than having one silently chosen for them.
    """
    memberships = MembershipRepository(session)
    user_id = uuid.UUID(user.id)

    if x_organization_id:
        try:
            organization_id = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise NotFound("Organization not found.") from exc
        role = await memberships.role_in(user_id, organization_id)
        if role is None:
            # Not 403: a caller must not learn that an organization exists.
            raise NotFound("Organization not found.")
        return Principal(user=user, organization_id=str(organization_id), role=Role(role))

    owned = await memberships.organizations_for_user(user_id)
    if not owned:
        raise Forbidden("You do not belong to any organization yet.")
    if len(owned) > 1:
        raise Forbidden(
            f"You belong to several organizations. Send the {ORGANIZATION_HEADER} header.",
            details={"organizations": [str(org.id) for org, _ in owned]},
        )
    organization, role = owned[0]
    return Principal(user=user, organization_id=str(organization.id), role=Role(role))


PrincipalDep = Annotated[Principal, Depends(get_principal)]


# ---------------------------------------------------------------------------
# Providers. Injected, never imported by name in a route or service.
# ---------------------------------------------------------------------------
def get_storage_provider() -> StorageProvider:
    return build_storage_provider(get_settings())


def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())


def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())


GenerationRunner = Callable[..., Awaitable[None]]


def get_generation_runner() -> GenerationRunner:
    """How a route schedules background generation.

    A dependency rather than a direct import so it can be replaced: the test
    harness runs inside a transaction that is rolled back, so a background task
    opening its own session would find nothing and leave a connection behind.
    Tests override this with a no-op and drive the runner directly instead,
    which exercises the same code without the dangling connection.
    """
    from app.services.generation import run_batch_in_background

    return run_batch_in_background


GenerationRunnerDep = Annotated[GenerationRunner, Depends(get_generation_runner)]


def get_evaluation_runner() -> GenerationRunner:
    """How a route schedules background evaluation.

    A dependency for the same reason generation's is: the test harness runs
    inside a transaction that is rolled back, so a background task opening its
    own session would find nothing and leave a connection behind.
    """
    from app.services.evaluation_stage import run_evaluations_in_background

    return run_evaluations_in_background


EvaluationRunnerDep = Annotated[GenerationRunner, Depends(get_evaluation_runner)]


def get_guardian_runner() -> GenerationRunner:
    """How a route schedules background brand checks. A dependency for the same
    reason the other two are: the test harness replaces it."""
    from app.services.revision_stage import run_guardian_in_background

    return run_guardian_in_background


GuardianRunnerDep = Annotated[GenerationRunner, Depends(get_guardian_runner)]
StorageDep = Annotated[StorageProvider, Depends(get_storage_provider)]
EmbeddingsDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
