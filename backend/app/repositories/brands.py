"""Brand Brain persistence.

Every repository here extends `OrganizationOwnedRepository`, so the tenancy
guarantee is the one established in Milestone 1 and audited in
`M1_SECURITY_AUDIT.md` — scope is applied by the base class, on every query,
and cannot be forgotten per call site.

Brand knowledge is the most sensitive thing this product stores: a competitor's
positioning, claims and guidelines. `BrandChunkRepository` therefore scopes
twice — organization *and* brand — because a similarity search that forgot
either would silently return another tenant's brand strategy ranked by how
relevant it is.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, delete, func, select

from app.db.models import (
    BrandAssetRow,
    BrandChunkRow,
    BrandDocumentRow,
    BrandFactRow,
    BrandProfileRow,
)
from app.domain.brand import DocumentStatus
from app.errors import Conflict
from app.repositories.base import OrganizationOwnedRepository
from app.repositories.pagination import DEFAULT_LIMIT, Page, keyset_page


class BrandRepository(OrganizationOwnedRepository[BrandProfileRow]):
    model = BrandProfileRow

    def _scope(self, stmt: Select[Any]) -> Select[Any]:
        """Organization scope plus soft-delete, exactly as projects do."""
        return super()._scope(stmt).where(BrandProfileRow.deleted_at.is_(None))

    async def list_page(
        self, *, limit: int = DEFAULT_LIMIT, cursor: str | None = None
    ) -> Page[BrandProfileRow]:
        """One page, still alphabetical.

        This was `list_all()`, which returned every brand in the organization
        (audit finding PERF-1). Campaign-scoped lists are bounded by one
        campaign's work; an organization's brand list grows with the tenant, so
        it is paged. Keyed on `(name, id)` so the order the screen already had
        is the order the cursor walks.
        """
        return await keyset_page(
            self.session, self.scoped(), BrandProfileRow, key="name", limit=limit, cursor=cursor
        )

    async def create(
        self, *, name: str, payload: dict[str, Any], created_by: uuid.UUID | None
    ) -> BrandProfileRow:
        from sqlalchemy.exc import IntegrityError

        row = BrandProfileRow(
            organization_id=self.organization_id,
            name=name,
            payload=payload,
            created_by=created_by,
        )
        # A savepoint, so a duplicate name rolls back only this insert. Without
        # it the constraint violation poisons the whole session and any caller
        # that wanted to handle the conflict would be unable to continue.
        savepoint = await self.session.begin_nested()
        self.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await savepoint.rollback()
            raise Conflict(f"A brand named {name!r} already exists in this workspace.") from exc
        return row

    async def update_payload(
        self, row: BrandProfileRow, *, name: str, payload: dict[str, Any]
    ) -> BrandProfileRow:
        row.name = name
        row.payload = payload
        await self.session.flush()
        return row

    async def soft_delete(self, row: BrandProfileRow) -> None:
        row.deleted_at = func.now()
        await self.session.flush()


class BrandDocumentRepository(OrganizationOwnedRepository[BrandDocumentRow]):
    model = BrandDocumentRow

    async def list_for_brand(self, brand_id: uuid.UUID) -> list[BrandDocumentRow]:
        stmt = (
            self.scoped()
            .where(BrandDocumentRow.brand_profile_id == brand_id)
            .order_by(BrandDocumentRow.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        brand_id: uuid.UUID,
        title: str,
        source_type: str,
        filename: str | None,
        mime_type: str | None,
        size_bytes: int | None,
        storage_key: str | None,
        content_sha256: str | None = None,
    ) -> BrandDocumentRow:
        row = BrandDocumentRow(
            organization_id=self.organization_id,
            brand_profile_id=brand_id,
            title=title,
            source_type=source_type,
            filename=filename,
            mime_type=mime_type,
            bytes=size_bytes,
            storage_key=storage_key,
            content_sha256=content_sha256,
            status=DocumentStatus.PENDING.value,
        )
        self.add(row)
        await self.session.flush()
        return row

    async def set_status(
        self,
        row: BrandDocumentRow,
        status: DocumentStatus,
        *,
        error: str | None = None,
        page_count: int | None = None,
        chunk_count: int | None = None,
    ) -> BrandDocumentRow:
        """The only way a document's status changes.

        `error` is cleared on every non-failure transition so a document that
        succeeds on retry does not keep displaying its previous failure.
        """
        row.status = status.value
        row.error = error if status.is_failure() else None
        if page_count is not None:
            row.page_count = page_count
        if chunk_count is not None:
            row.chunk_count = chunk_count
        await self.session.flush()
        return row

    async def find_by_digest(self, brand_id: uuid.UUID, digest: str) -> BrandDocumentRow | None:
        """Lets ingest skip a byte-identical re-upload instead of paying for
        extraction and embeddings again (§17)."""
        stmt = self.scoped().where(
            BrandDocumentRow.brand_profile_id == brand_id,
            BrandDocumentRow.content_sha256 == digest,
            BrandDocumentRow.status == DocumentStatus.COMPLETED.value,
        )
        return (await self.session.execute(stmt)).scalars().first()


class BrandAssetRepository(OrganizationOwnedRepository[BrandAssetRow]):
    model = BrandAssetRow

    async def list_for_brand(self, brand_id: uuid.UUID) -> list[BrandAssetRow]:
        stmt = (
            self.scoped()
            .where(BrandAssetRow.brand_profile_id == brand_id)
            .order_by(BrandAssetRow.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(
        self,
        *,
        brand_id: uuid.UUID,
        kind: str,
        storage_key: str,
        filename: str | None,
        mime_type: str,
        size_bytes: int | None,
        width: int | None = None,
        height: int | None = None,
    ) -> BrandAssetRow:
        row = BrandAssetRow(
            organization_id=self.organization_id,
            brand_profile_id=brand_id,
            kind=kind,
            storage_key=storage_key,
            filename=filename,
            mime_type=mime_type,
            bytes=size_bytes,
            width=width,
            height=height,
        )
        self.add(row)
        await self.session.flush()
        return row


class BrandChunkRepository(OrganizationOwnedRepository[BrandChunkRow]):
    """Vector knowledge. The highest-value cross-tenant target in the system."""

    model = BrandChunkRow

    async def replace_for_document(
        self, *, brand_id: uuid.UUID, document_id: uuid.UUID, chunks: list[dict[str, Any]]
    ) -> int:
        """Delete-then-insert, so re-ingesting a document cannot leave stale
        chunks behind that retrieval would still happily return.

        The delete is scoped: a document id from another organization matches
        nothing and removes nothing.
        """
        await self.session.execute(
            delete(BrandChunkRow).where(
                BrandChunkRow.organization_id == self.organization_id,
                BrandChunkRow.brand_document_id == document_id,
            )
        )
        for chunk in chunks:
            self.add(
                BrandChunkRow(
                    organization_id=self.organization_id,
                    brand_profile_id=brand_id,
                    brand_document_id=document_id,
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    page=chunk.get("page"),
                    embedding=chunk["embedding"],
                )
            )
        await self.session.flush()
        return len(chunks)

    async def search(
        self, *, brand_id: uuid.UUID, embedding: list[float], top_k: int = 5
    ) -> list[tuple[BrandChunkRow, float]]:
        """Cosine-nearest chunks for one brand.

        Scoped by organization (via `scoped()`) **and** by brand. Either filter
        alone would be a leak: without the organization filter a caller reaches
        another tenant; without the brand filter they reach another brand in
        their own workspace, which is still a confidentiality failure for an
        agency holding competing clients.
        """
        top_k = max(1, min(top_k, 50))
        distance = BrandChunkRow.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            self._scope(select(BrandChunkRow, distance))
            .where(
                BrandChunkRow.brand_profile_id == brand_id,
                BrandChunkRow.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(top_k)
        )
        rows = (await self.session.execute(stmt)).all()
        # Cosine distance 0..2 -> similarity 1..-1, clamped to 0..1 for display.
        return [(row, max(0.0, 1.0 - float(dist))) for row, dist in rows]

    async def count_for_brand(self, brand_id: uuid.UUID) -> int:
        stmt = self._scope(select(func.count()).select_from(BrandChunkRow)).where(
            BrandChunkRow.brand_profile_id == brand_id
        )
        return int((await self.session.execute(stmt)).scalar_one())


class BrandFactRepository(OrganizationOwnedRepository[BrandFactRow]):
    """AI proposals. Nothing here is authoritative until a human accepts it."""

    model = BrandFactRow

    async def list_for_brand(
        self, brand_id: uuid.UUID, *, status: str | None = None
    ) -> list[BrandFactRow]:
        stmt = self.scoped().where(BrandFactRow.brand_profile_id == brand_id)
        if status is not None:
            stmt = stmt.where(BrandFactRow.status == status)
        stmt = stmt.order_by(BrandFactRow.confidence.desc(), BrandFactRow.field)
        return list((await self.session.execute(stmt)).scalars().all())

    async def replace_for_document(
        self, *, brand_id: uuid.UUID, document_id: uuid.UUID | None, facts: list[dict[str, Any]]
    ) -> int:
        """Re-analysing a document supersedes its previous proposals.

        Accepted and rejected facts are preserved — a human decision is not
        undone by re-running extraction.
        """
        await self.session.execute(
            delete(BrandFactRow).where(
                BrandFactRow.organization_id == self.organization_id,
                BrandFactRow.brand_document_id == document_id,
                BrandFactRow.status == "proposed",
            )
        )
        for fact in facts:
            self.add(
                BrandFactRow(
                    organization_id=self.organization_id,
                    brand_profile_id=brand_id,
                    brand_document_id=document_id,
                    field=fact["field"],
                    value=fact["value"],
                    confidence=fact["confidence"],
                    status=fact.get("status", "proposed"),
                    provenance=fact["provenance"],
                    rationale=fact.get("rationale"),
                )
            )
        await self.session.flush()
        return len(facts)

    async def set_status(self, row: BrandFactRow, status: str) -> BrandFactRow:
        row.status = status
        await self.session.flush()
        return row
