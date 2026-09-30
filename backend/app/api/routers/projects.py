"""Projects.

Every handler is thin: resolve scope, call the repository, map to the domain
model. The organization filter is never written here — it is applied by
`ScopedRepository`, which is the only way it can be guaranteed for all 23
tables (DATABASE_SCHEMA §Tenancy).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.authz import ManageWorkspaceDep
from app.api.deps import PrincipalDep, SessionDep
from app.api.schemas import CreateProjectRequest, ProjectPage, UpdateProjectRequest
from app.domain.workspace import Project
from app.errors import NotFound, ValidationFailed
from app.repositories.projects import ProjectRepository

router = APIRouter(prefix="/projects", tags=["projects"])


def _to_domain(row: object) -> Project:
    return Project(
        id=str(row.id),  # type: ignore[attr-defined]
        organization_id=str(row.organization_id),  # type: ignore[attr-defined]
        name=row.name,  # type: ignore[attr-defined]
        description=row.description,  # type: ignore[attr-defined]
    )


def _repo(principal: PrincipalDep, session: SessionDep) -> ProjectRepository:
    return ProjectRepository(session, uuid.UUID(principal.organization_id))


def _parse_id(project_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_id)
    except ValueError as exc:
        # A malformed id cannot name a real project — 404, not 400, so probing
        # ids tells an attacker nothing either way.
        raise NotFound("Project not found.") from exc


@router.get("", response_model=ProjectPage)
async def list_projects(
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ProjectPage:
    page = await _repo(principal, session).list_page(limit=limit, cursor=cursor)
    return ProjectPage(items=[_to_domain(row) for row in page.items], next_cursor=page.next_cursor)


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectRequest, principal: ManageWorkspaceDep, session: SessionDep
) -> Project:
    row = await _repo(principal, session).create(
        name=body.name, description=body.description, created_by=uuid.UUID(principal.user.id)
    )
    return _to_domain(row)


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, principal: PrincipalDep, session: SessionDep) -> Project:
    row = await _repo(principal, session).get(_parse_id(project_id))
    if row is None:
        raise NotFound("Project not found.")
    return _to_domain(row)


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    project_id: str, body: UpdateProjectRequest, principal: ManageWorkspaceDep, session: SessionDep
) -> Project:
    repo = _repo(principal, session)
    row = await repo.get(_parse_id(project_id))
    if row is None:
        raise NotFound("Project not found.")
    if body.name is None and body.description is None:
        raise ValidationFailed("Nothing to update.", details={"field": "body"})
    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    await session.flush()
    return _to_domain(row)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str, principal: ManageWorkspaceDep, session: SessionDep
) -> None:
    repo = _repo(principal, session)
    row = await repo.get(_parse_id(project_id))
    if row is None:
        raise NotFound("Project not found.")
    await repo.soft_delete(row)
