"""Brand endpoints.

Thin, like the Milestone 1 routers: resolve scope, call a service, map to a
typed response. Every handler reaches the database through `BrandService`,
which resolves the brand via the organization-scoped repository — so a brand id
from another organization is a 404 here exactly as a project id is.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.authz import EditBrandDep
from app.api.deps import PrincipalDep, SessionDep
from app.api.schemas import (
    BrandList,
    CreateBrandRequest,
    UpdateBrandRequest,
)
from app.domain.brand import BrandProfile
from app.errors import NotFound, ValidationFailed
from app.repositories.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.services.brands import BrandService

router = APIRouter(prefix="/brands", tags=["brands"])


def _brand_id(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        # A malformed id cannot name a real brand — 404, so probing ids tells
        # an attacker nothing either way (API_SPEC §Scope).
        raise NotFound("Brand not found.") from exc


def _service(principal: PrincipalDep, session: SessionDep) -> BrandService:
    return BrandService(session, principal)


@router.get("", response_model=BrandList)
async def list_brands(
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None),
) -> BrandList:
    """One page, alphabetical. `?limit=&cursor=` as API_SPEC §Lists describes."""
    page = await _service(principal, session).list_brands(limit=limit, cursor=cursor)
    return BrandList(items=page.items, next_cursor=page.next_cursor)


@router.post("", response_model=BrandProfile, status_code=status.HTTP_201_CREATED)
async def create_brand(
    body: CreateBrandRequest, principal: EditBrandDep, session: SessionDep
) -> BrandProfile:
    return await _service(principal, session).create(body.model_dump(exclude_unset=True))


@router.get("/{brand_id}", response_model=BrandProfile)
async def get_brand(brand_id: str, principal: PrincipalDep, session: SessionDep) -> BrandProfile:
    return await _service(principal, session).get(_brand_id(brand_id))


@router.patch("/{brand_id}", response_model=BrandProfile)
async def update_brand(
    brand_id: str, body: UpdateBrandRequest, principal: EditBrandDep, session: SessionDep
) -> BrandProfile:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise ValidationFailed("Nothing to update.", details={"field": "body"})
    return await _service(principal, session).update(_brand_id(brand_id), fields)


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(brand_id: str, principal: EditBrandDep, session: SessionDep) -> None:
    await _service(principal, session).delete(_brand_id(brand_id))
