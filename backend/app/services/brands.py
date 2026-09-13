"""Brand profile use-cases.

The service owns the mapping between the typed domain `BrandProfile` and the
`brand_profiles` row that stores it as JSONB. Routes never touch the payload
directly, so validation happens in exactly one place.

One rule worth stating: identity comes from the **columns**, never the payload.
`id` and `organization_id` are re-stamped from the row on every read, so a
payload that somehow carried a different organization cannot misreport
ownership to anything downstream.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrandProfileRow
from app.domain.brand import BrandProfile
from app.domain.workspace import Principal
from app.errors import NotFound
from app.repositories.brands import BrandRepository

#: Fields a client may set. `id` and `organization_id` are deliberately absent.
EDITABLE_FIELDS = frozenset(
    {
        "name",
        "industry",
        "description",
        "website",
        "positioning",
        "mission",
        "values",
        "audience_description",
        "voice",
        "colors",
        "typography",
        "preferred_styles",
        "products",
        "approved_claims",
        "prohibited_claims",
        "visual_dos",
        "visual_donts",
        "logo_rules",
        "legal_line",
    }
)


def row_to_profile(row: BrandProfileRow) -> BrandProfile:
    """Rebuild the typed profile, with identity taken from the columns."""
    payload = dict(row.payload or {})
    payload["id"] = str(row.id)
    payload["organization_id"] = str(row.organization_id)
    payload["name"] = row.name
    return BrandProfile.model_validate(payload)


def profile_to_payload(profile: BrandProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json")


class BrandService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal
        self.organization_id = uuid.UUID(principal.organization_id)
        self.repo = BrandRepository(session, self.organization_id)

    async def _row(self, brand_id: uuid.UUID) -> BrandProfileRow:
        row = await self.repo.get(brand_id)
        if row is None:
            # Indistinguishable from another organization's brand, by design.
            raise NotFound("Brand not found.")
        return row

    async def list_brands(self) -> list[BrandProfile]:
        return [row_to_profile(r) for r in await self.repo.list_all()]

    async def get(self, brand_id: uuid.UUID) -> BrandProfile:
        return row_to_profile(await self._row(brand_id))

    async def get_row(self, brand_id: uuid.UUID) -> BrandProfileRow:
        """For services that need the row itself (documents, knowledge).

        Going through here means every one of them inherits the scope check
        rather than re-implementing it.
        """
        return await self._row(brand_id)

    async def create(self, fields: dict[str, Any]) -> BrandProfile:
        clean = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS and v is not None}
        name = str(clean.pop("name"))
        # Validate before writing: a profile that cannot be reconstructed must
        # never reach the database.
        profile = BrandProfile.model_validate(
            {
                "id": str(uuid.uuid4()),
                "organization_id": str(self.organization_id),
                "name": name,
                **clean,
            }
        )
        row = await self.repo.create(
            name=name,
            payload=profile_to_payload(profile),
            created_by=uuid.UUID(self.principal.user.id),
        )
        return row_to_profile(row)

    async def update(self, brand_id: uuid.UUID, fields: dict[str, Any]) -> BrandProfile:
        """Partial update. Absent keys are left alone; an explicit null clears."""
        row = await self._row(brand_id)
        current = row_to_profile(row).model_dump(mode="json")
        for key, value in fields.items():
            if key in EDITABLE_FIELDS:
                current[key] = value
        profile = BrandProfile.model_validate(current)
        await self.repo.update_payload(row, name=profile.name, payload=profile_to_payload(profile))
        return row_to_profile(row)

    async def delete(self, brand_id: uuid.UUID) -> None:
        await self.repo.soft_delete(await self._row(brand_id))
