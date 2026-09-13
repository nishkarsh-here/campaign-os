"""Document ingest: upload, extract, chunk, embed, analyse.

The pipeline runs as a background task so an upload returns immediately and the
UI can show real progress instead of an unexplained wait (§17). Every stage has
its own terminal failure state, so a document that fails at embedding says so
rather than sitting at "processing" forever — and nothing is ever marked
COMPLETED by a stage that did not finish (§18).

    PENDING -> EXTRACTING -> EMBEDDING -> COMPLETED
                  |              |
                  v              v
         EXTRACTION_FAILED  EMBEDDING_FAILED

Vendors appear nowhere here: text comes from `app.services.extraction`, vectors
from the injected `EmbeddingProvider`, facts from the injected `LLMProvider`.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BrandDocumentRow
from app.domain.brand import BrandExtraction, DocumentStatus, ProvenanceKind
from app.logging import get_logger
from app.providers.base import EmbeddingProvider, LLMProvider, ProviderError, StorageProvider
from app.repositories.brands import (
    BrandChunkRepository,
    BrandDocumentRepository,
    BrandFactRepository,
)
from app.services.extraction import ExtractionError, extract
from app.services.uploads import ValidatedUpload, storage_key_for

log = get_logger(__name__)

#: Bounded so one enormous document cannot monopolise a provider call.
EMBED_BATCH = 32

EXTRACTION_SYSTEM = (
    "You extract brand facts from source material. Quote only what the sources "
    "actually say. Never invent a fact to fill a field — list it as unknown instead."
)


def build_extraction_prompt(brand_name: str, sources: list[str]) -> str:
    body = "\n\n---\n\n".join(sources)
    return (
        f"Brand: {brand_name}\n\n"
        "Extract candidate brand facts from the sources below. Every fact must be "
        "supported by the text. Where the sources are silent, say so.\n\n"
        f"SOURCES:\n{body}"
    )


class BrandDocumentService:
    """Upload and processing. Holds no request state, so the same object works
    inside a request and inside a background task."""

    def __init__(
        self,
        session: AsyncSession,
        organization_id: uuid.UUID,
        *,
        storage: StorageProvider,
        embeddings: EmbeddingProvider,
        llm: LLMProvider,
    ) -> None:
        self.session = session
        self.organization_id = organization_id
        self.storage = storage
        self.embeddings = embeddings
        self.llm = llm
        self.documents = BrandDocumentRepository(session, organization_id)
        self.chunks = BrandChunkRepository(session, organization_id)
        self.facts = BrandFactRepository(session, organization_id)

    # ------------------------------------------------------------------ upload
    async def upload(
        self, *, brand_id: uuid.UUID, upload: ValidatedUpload, title: str | None
    ) -> BrandDocumentRow:
        """Persist the bytes, then the row. Returns immediately — processing is
        the caller's next step, in the background."""
        existing = await self.documents.find_by_digest(brand_id, upload.sha256)
        if existing is not None:
            # Byte-identical re-upload: reuse rather than pay for extraction and
            # embeddings again (§17).
            log.info("document_deduplicated", document_id=str(existing.id))
            return existing

        source_type = "pdf" if upload.mime_type == "application/pdf" else "text"
        key = storage_key_for(
            organization_id=self.organization_id,
            brand_id=brand_id,
            kind="documents",
            extension=upload.filename.rsplit(".", 1)[-1] if "." in upload.filename else "bin",
        )
        try:
            await self.storage.put(key, upload.data, mime_type=upload.mime_type)
        except ProviderError as exc:
            log.error("document_storage_failed", detail=exc.detail, provider=exc.provider)
            raise

        return await self.documents.create(
            brand_id=brand_id,
            title=title or upload.filename,
            source_type=source_type,
            filename=upload.filename,
            mime_type=upload.mime_type,
            size_bytes=upload.size_bytes,
            storage_key=key,
            content_sha256=upload.sha256,
        )

    async def create_text_document(
        self, *, brand_id: uuid.UUID, title: str, content: str
    ) -> BrandDocumentRow:
        """Pasted text — no file, but the same pipeline afterwards."""
        import hashlib

        data = content.encode("utf-8")
        key = storage_key_for(
            organization_id=self.organization_id,
            brand_id=brand_id,
            kind="documents",
            extension="txt",
        )
        await self.storage.put(key, data, mime_type="text/plain")
        return await self.documents.create(
            brand_id=brand_id,
            title=title,
            source_type="text",
            filename=None,
            mime_type="text/plain",
            size_bytes=len(data),
            storage_key=key,
            content_sha256=hashlib.sha256(data).hexdigest(),
        )

    # -------------------------------------------------------------- processing
    async def process(self, document_id: uuid.UUID) -> DocumentStatus:
        """Run the pipeline for one document. Never raises: every failure is
        recorded as a terminal status the UI can explain and a user can retry."""
        row = await self.documents.get(document_id)
        if row is None:
            # Scoped lookup: another organization's id resolves to nothing.
            return DocumentStatus.EXTRACTION_FAILED

        try:
            data = await self.storage.get(row.storage_key or "")
        except ProviderError as exc:
            return await self._fail(
                row, DocumentStatus.UPLOAD_FAILED, "The stored file could not be read.", exc.detail
            )

        # --- extract -------------------------------------------------------
        await self.documents.set_status(row, DocumentStatus.EXTRACTING)
        try:
            extracted = extract(data, mime_type=row.mime_type or "text/plain")
        except ExtractionError as exc:
            return await self._fail(row, DocumentStatus.EXTRACTION_FAILED, exc.message, exc.detail)

        if extracted.is_empty:
            message = (
                "No text could be read from this document. It looks like scanned "
                "images, and text recognition is not available yet."
                if extracted.needs_ocr
                else "This document contains no readable text."
            )
            return await self._fail(row, DocumentStatus.EXTRACTION_FAILED, message, None)

        # --- embed ---------------------------------------------------------
        await self.documents.set_status(
            row, DocumentStatus.EMBEDDING, page_count=extracted.page_count
        )
        try:
            vectors: list[list[float]] = []
            contents = [p.content for p in extracted.passages]
            for start in range(0, len(contents), EMBED_BATCH):
                vectors.extend(await self.embeddings.embed(contents[start : start + EMBED_BATCH]))
        except ProviderError as exc:
            return await self._fail(
                row,
                DocumentStatus.EMBEDDING_FAILED,
                "Brand knowledge could not be indexed. Try again in a moment.",
                exc.detail,
            )

        await self.chunks.replace_for_document(
            brand_id=row.brand_profile_id,
            document_id=row.id,
            chunks=[
                {
                    "chunk_index": passage.index,
                    "content": passage.content,
                    "page": passage.page,
                    "embedding": vector,
                }
                for passage, vector in zip(extracted.passages, vectors, strict=True)
            ],
        )

        # --- analyse -------------------------------------------------------
        # Deliberately last and non-fatal: knowledge is already searchable, so a
        # model failure must not discard it.
        try:
            await self._extract_facts(row, extracted.text)
        except ProviderError as exc:
            log.warning("brand_analysis_failed", document_id=str(row.id), detail=exc.detail)
            await self.documents.set_status(
                row,
                DocumentStatus.COMPLETED,
                chunk_count=len(extracted.passages),
                page_count=extracted.page_count,
            )
            return DocumentStatus.COMPLETED

        await self.documents.set_status(
            row,
            DocumentStatus.COMPLETED,
            chunk_count=len(extracted.passages),
            page_count=extracted.page_count,
        )
        return DocumentStatus.COMPLETED

    async def _extract_facts(self, row: BrandDocumentRow, text: str) -> BrandExtraction:
        """Structured extraction. Output is validated by the provider against
        `BrandExtraction`, and every fact lands as a PROPOSAL."""
        from app.db.models import BrandProfileRow

        brand = await self.session.get(BrandProfileRow, row.brand_profile_id)
        brand_name = brand.name if brand else "this brand"
        # Bounded: the prompt carries a readable slice, not an entire book.
        result = await self.llm.structured(
            build_extraction_prompt(brand_name, [text[:20_000]]),
            BrandExtraction,
            system=EXTRACTION_SYSTEM,
        )
        await self.facts.replace_for_document(
            brand_id=row.brand_profile_id,
            document_id=row.id,
            facts=[
                {
                    "field": fact.field,
                    "value": fact.value,
                    "confidence": fact.confidence,
                    "status": fact.status.value,
                    "provenance": fact.provenance.model_copy(
                        update={
                            "kind": fact.provenance.kind or ProvenanceKind.DOCUMENT,
                            "document_id": str(row.id),
                            "document_title": row.title,
                        }
                    ).model_dump(mode="json"),
                    "rationale": fact.rationale,
                }
                for fact in result.facts
            ],
        )
        return result

    async def _fail(
        self, row: BrandDocumentRow, status: DocumentStatus, message: str, detail: str | None
    ) -> DocumentStatus:
        """Record a terminal failure. `message` is user-safe; `detail` is logged
        and never stored on the row."""
        log.warning(
            "document_processing_failed",
            document_id=str(row.id),
            status=status.value,
            detail=detail,
        )
        await self.documents.set_status(row, status, error=message)
        return status


async def process_document_in_background(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    storage: StorageProvider,
    embeddings: EmbeddingProvider,
    llm: LLMProvider,
) -> None:
    """Entry point for the background task.

    Opens its own session: the request's session is closed by the time this
    runs. Commits explicitly, because nothing else will.
    """
    async with sessionmaker() as session:
        service = BrandDocumentService(
            session, organization_id, storage=storage, embeddings=embeddings, llm=llm
        )
        try:
            await service.process(document_id)
            await session.commit()
        except Exception:  # noqa: BLE001 - a background task must not vanish silently
            await session.rollback()
            log.exception("document_background_task_failed", document_id=str(document_id))
            async with sessionmaker() as recovery:
                documents = BrandDocumentRepository(recovery, organization_id)
                row = await documents.get(document_id)
                if row is not None and not DocumentStatus(row.status).is_terminal():
                    # Never leave a row stuck mid-pipeline (§18).
                    await documents.set_status(
                        row,
                        DocumentStatus.EXTRACTION_FAILED,
                        error="Processing stopped unexpectedly. Please try again.",
                    )
                    await recovery.commit()
