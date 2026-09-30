"""Brand documents, assets, knowledge and the Brand Brain view.

Uploads return `202` with the document row: the pipeline runs in the
background, and the client polls the document's status (API_SPEC §Polling).
That is why every stage has a distinct terminal state — the UI reads it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from fastapi.responses import Response

from app.api.authz import EditBrandDep
from app.api.deps import (
    EmbeddingsDep,
    LLMDep,
    MediaLinkDep,
    PrincipalDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    media_access,
)
from app.api.media_links import MediaKind, MediaLink
from app.api.schemas import (
    AssetList,
    BrandAssetSummary,
    BrandBrainView,
    BrandDocumentSummary,
    CreateTextDocumentRequest,
    DocumentList,
    FactDecisionRequest,
    FactList,
    FactSummary,
    KnowledgeHit,
    KnowledgeQuery,
    KnowledgeResult,
)
from app.db.models import BrandAssetRow, BrandDocumentRow, BrandFactRow, BrandProfileRow
from app.db.session import get_sessionmaker
from app.domain.brand import DocumentStatus, FactStatus, Provenance
from app.domain.workspace import Principal
from app.errors import NotFound, ValidationFailed
from app.repositories.brands import BrandDocumentRepository
from app.services.brand_documents import (
    BrandDocumentService,
    process_document_in_background,
)
from app.services.brand_knowledge import BrandBrainService, BrandKnowledgeRetriever
from app.services.brands import BrandService
from app.services.uploads import IMAGE_MIMES, PDF_MIME, TEXT_MIMES, validate_upload

router = APIRouter(prefix="/brands/{brand_id}", tags=["brand-brain"])

DOCUMENT_MIMES = frozenset({PDF_MIME, *TEXT_MIMES})
ASSET_KINDS = frozenset({"logo", "logo_mono", "product", "font", "pattern", "other"})


def _uuid(raw: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise NotFound(f"{what} not found.") from exc


def _document_summary(row: BrandDocumentRow) -> BrandDocumentSummary:
    return BrandDocumentSummary(
        id=str(row.id),
        brand_id=str(row.brand_profile_id),
        title=row.title,
        source_type=row.source_type,
        filename=row.filename,
        mime_type=row.mime_type,
        bytes=row.bytes,
        status=DocumentStatus(row.status),
        page_count=row.page_count,
        chunk_count=row.chunk_count,
        error=row.error,
        created_at=row.created_at,
    )


def _asset_summary(row: BrandAssetRow, link: MediaLink) -> BrandAssetSummary:
    return BrandAssetSummary(
        id=str(row.id),
        brand_id=str(row.brand_profile_id),
        kind=row.kind,
        filename=row.filename,
        mime_type=row.mime_type,
        bytes=row.bytes,
        width=row.width,
        height=row.height,
        # Served through the API so scope is checked on read; the browser never
        # addresses storage directly. Signed and short-lived, because an
        # `<img src>` cannot carry the headers that normally prove that scope.
        url=link.brand_asset(row.brand_profile_id, row.id),
    )


def _fact_summary(row: BrandFactRow) -> FactSummary:
    return FactSummary(
        id=str(row.id),
        field=row.field,
        value=row.value,
        confidence=row.confidence,
        status=FactStatus(row.status),
        provenance=Provenance.model_validate(row.provenance or {"kind": "inferred"}),
        rationale=row.rationale,
    )


async def _scoped_brand(
    principal: PrincipalDep, session: SessionDep, brand_id: str
) -> BrandProfileRow:
    """Resolve the brand through the scoped service, so every route below
    inherits the tenancy check rather than repeating it."""
    return await BrandService(session, principal).get_row(_uuid(brand_id, "Brand"))


# --------------------------------------------------------------------- documents
@router.get("/documents", response_model=DocumentList)
async def list_documents(
    brand_id: str, principal: PrincipalDep, session: SessionDep
) -> DocumentList:
    brand = await _scoped_brand(principal, session, brand_id)
    # The repository directly: listing documents needs no embedding provider.
    repo = BrandDocumentRepository(session, uuid.UUID(principal.organization_id))
    return DocumentList(items=[_document_summary(r) for r in await repo.list_for_brand(brand.id)])


@router.post(
    "/documents", response_model=BrandDocumentSummary, status_code=status.HTTP_202_ACCEPTED
)
async def upload_document(
    brand_id: str,
    principal: EditBrandDep,
    session: SessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    embeddings: EmbeddingsDep,
    llm: LLMDep,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
) -> BrandDocumentSummary:
    brand = await _scoped_brand(principal, session, brand_id)
    upload = validate_upload(
        await file.read(),
        declared_mime=file.content_type,
        filename=file.filename,
        allowed=DOCUMENT_MIMES,
        max_bytes=settings.max_upload_bytes,
    )
    organization_id = uuid.UUID(principal.organization_id)
    service = BrandDocumentService(
        session, organization_id, storage=storage, embeddings=embeddings, llm=llm
    )
    row = await service.upload(brand_id=brand.id, upload=upload, title=title)

    if DocumentStatus(row.status) is DocumentStatus.PENDING:
        await session.commit()  # the background task needs to see the row
        background.add_task(
            process_document_in_background,
            get_sessionmaker(),
            organization_id=organization_id,
            document_id=row.id,
            storage=storage,
            embeddings=embeddings,
            llm=llm,
        )
    return _document_summary(row)


@router.post(
    "/documents/text", response_model=BrandDocumentSummary, status_code=status.HTTP_202_ACCEPTED
)
async def create_text_document(
    brand_id: str,
    body: CreateTextDocumentRequest,
    principal: EditBrandDep,
    session: SessionDep,
    storage: StorageDep,
    embeddings: EmbeddingsDep,
    llm: LLMDep,
    background: BackgroundTasks,
) -> BrandDocumentSummary:
    brand = await _scoped_brand(principal, session, brand_id)
    organization_id = uuid.UUID(principal.organization_id)
    service = BrandDocumentService(
        session, organization_id, storage=storage, embeddings=embeddings, llm=llm
    )
    row = await service.create_text_document(
        brand_id=brand.id, title=body.title, content=body.content
    )
    await session.commit()
    background.add_task(
        process_document_in_background,
        get_sessionmaker(),
        organization_id=organization_id,
        document_id=row.id,
        storage=storage,
        embeddings=embeddings,
        llm=llm,
    )
    return _document_summary(row)


@router.get("/documents/{document_id}", response_model=BrandDocumentSummary)
async def get_document(
    brand_id: str, document_id: str, principal: PrincipalDep, session: SessionDep
) -> BrandDocumentSummary:
    brand = await _scoped_brand(principal, session, brand_id)
    from app.repositories.brands import BrandDocumentRepository

    repo = BrandDocumentRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.get(_uuid(document_id, "Document"))
    if row is None or row.brand_profile_id != brand.id:
        raise NotFound("Document not found.")
    return _document_summary(row)


# ------------------------------------------------------------------------ assets
@router.get("/assets", response_model=AssetList)
async def list_assets(
    brand_id: str, principal: PrincipalDep, link: MediaLinkDep, session: SessionDep
) -> AssetList:
    brand = await _scoped_brand(principal, session, brand_id)
    from app.repositories.brands import BrandAssetRepository

    repo = BrandAssetRepository(session, uuid.UUID(principal.organization_id))
    return AssetList(items=[_asset_summary(r, link) for r in await repo.list_for_brand(brand.id)])


@router.post("/assets", response_model=BrandAssetSummary, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    brand_id: str,
    principal: EditBrandDep,
    session: SessionDep,
    link: MediaLinkDep,
    settings: SettingsDep,
    storage: StorageDep,
    file: UploadFile = File(...),
    kind: str = Form(default="other"),
) -> BrandAssetSummary:
    brand = await _scoped_brand(principal, session, brand_id)
    if kind not in ASSET_KINDS:
        raise ValidationFailed(
            f"{kind!r} is not a brand asset kind.",
            details={"field": "kind", "allowed": sorted(ASSET_KINDS)},
        )
    upload = validate_upload(
        await file.read(),
        declared_mime=file.content_type,
        filename=file.filename,
        allowed=frozenset(IMAGE_MIMES),
        max_bytes=settings.max_upload_bytes,
    )
    from app.repositories.brands import BrandAssetRepository
    from app.services.uploads import storage_key_for

    organization_id = uuid.UUID(principal.organization_id)
    key = storage_key_for(
        organization_id=organization_id,
        brand_id=brand.id,
        kind="assets",
        extension=upload.filename.rsplit(".", 1)[-1] if "." in upload.filename else "bin",
    )
    await storage.put(key, upload.data, mime_type=upload.mime_type)
    row = await BrandAssetRepository(session, organization_id).create(
        brand_id=brand.id,
        kind=kind,
        storage_key=key,
        filename=upload.filename,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
    )
    return _asset_summary(row, link)


@router.get("/assets/{asset_id}/content")
async def get_asset_content(
    brand_id: str,
    asset_id: str,
    principal: Annotated[Principal, Depends(media_access(MediaKind.BRAND_ASSET, "asset_id"))],
    session: SessionDep,
    storage: StorageDep,
) -> Response:
    """Serve asset bytes through the API.

    The storage key is read from a scope-checked row — never from the request —
    so a key belonging to another organization cannot be requested at all.

    The caller proves themselves with the usual headers or with a signed link
    bound to this asset; a browser can send neither header on an `<img src>`.
    """
    from app.repositories.brands import BrandAssetRepository

    brand = await _scoped_brand(principal, session, brand_id)
    repo = BrandAssetRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.get(_uuid(asset_id, "Asset"))
    if row is None or row.brand_profile_id != brand.id:
        raise NotFound("Asset not found.")
    return Response(content=await storage.get(row.storage_key), media_type=row.mime_type)


# --------------------------------------------------------------------- knowledge
@router.post("/knowledge/query", response_model=KnowledgeResult)
async def query_knowledge(
    brand_id: str,
    body: KnowledgeQuery,
    principal: PrincipalDep,
    session: SessionDep,
    embeddings: EmbeddingsDep,
) -> KnowledgeResult:
    brand = await _scoped_brand(principal, session, brand_id)
    retriever = BrandKnowledgeRetriever(
        session, uuid.UUID(principal.organization_id), embeddings=embeddings
    )
    hits = await retriever.retrieve(brand_id=brand.id, query=body.query, top_k=body.top_k)
    return KnowledgeResult(
        query=body.query,
        hits=[
            KnowledgeHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                document_title=h.document_title,
                content=h.content,
                score=h.score,
                chunk_index=h.chunk_index,
                page=h.page,
            )
            for h in hits
        ],
    )


# ------------------------------------------------------------------------- facts
@router.get("/facts", response_model=FactList)
async def list_facts(brand_id: str, principal: PrincipalDep, session: SessionDep) -> FactList:
    brand = await _scoped_brand(principal, session, brand_id)
    from app.repositories.brands import BrandFactRepository

    repo = BrandFactRepository(session, uuid.UUID(principal.organization_id))
    return FactList(items=[_fact_summary(r) for r in await repo.list_for_brand(brand.id)])


@router.patch("/facts/{fact_id}", response_model=FactSummary)
async def decide_fact(
    brand_id: str,
    fact_id: str,
    body: FactDecisionRequest,
    principal: EditBrandDep,
    session: SessionDep,
) -> FactSummary:
    """Accept or reject a proposal.

    Accepting is the only route by which model output becomes a confirmed brand
    fact, and it is an explicit human act.
    """
    brand = await _scoped_brand(principal, session, brand_id)
    from app.repositories.brands import BrandFactRepository

    repo = BrandFactRepository(session, uuid.UUID(principal.organization_id))
    row = await repo.get(_uuid(fact_id, "Fact"))
    if row is None or row.brand_profile_id != brand.id:
        raise NotFound("Fact not found.")
    return _fact_summary(await repo.set_status(row, body.status.value))


# ------------------------------------------------------------------- brand brain
@router.get("/brain", response_model=BrandBrainView)
async def get_brand_brain(
    brand_id: str,
    principal: PrincipalDep,
    session: SessionDep,
    link: MediaLinkDep,
    embeddings: EmbeddingsDep,
) -> BrandBrainView:
    """Everything the Brand Brain page needs, in one call."""
    brand = await _scoped_brand(principal, session, brand_id)
    service = BrandBrainService(
        session, uuid.UUID(principal.organization_id), embeddings=embeddings
    )
    composed = await service.compose(brand)
    return BrandBrainView(
        brand=composed.profile,
        documents=[_document_summary(d) for d in composed.documents],
        assets=[_asset_summary(a, link) for a in composed.assets],
        proposed_facts=[_fact_summary(f) for f in composed.proposed_facts],
        field_status=composed.field_status,
        chunk_count=composed.chunk_count,
        knowledge_ready=composed.knowledge_ready,
        processing_errors=composed.processing_errors,
    )
