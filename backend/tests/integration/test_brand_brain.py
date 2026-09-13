"""The Brand Brain pipeline, end to end, on mock providers.

Covers ingest (upload -> extract -> chunk -> embed -> pgvector), retrieval, the
composed Brand Brain view, failure representation, and — the mandatory part —
that none of it crosses an organization or brand boundary.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models import BrandChunkRow, BrandProfileRow
from app.domain.brand import DocumentStatus
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.brands import BrandChunkRepository
from app.services.brand_documents import BrandDocumentService
from app.services.brand_knowledge import BrandKnowledgeRetriever
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

GUIDELINES = """Northline Materials brand guidelines.

Our positioning is engineered façade systems for architects who specify for the long term.

Our tone of voice is confident and technical. We avoid hype and superlatives.

We never claim our products are indestructible or carry a lifetime guarantee.

All products are tested to IS 456 standards and certified for structural use.

The logo must always keep clear space equal to the height of the N.
"""

LOGO_ONLY = """Logo usage rules.

The logo must never be stretched, rotated, or placed on a busy photograph.
"""


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "store"))


@pytest.fixture
def embeddings() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.fixture
def llm() -> MockLLMProvider:
    return MockLLMProvider()


async def _brand(session, org, name: str = "Northline") -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={"id": str(uuid.uuid4()), "organization_id": str(org.id), "name": name},
    )
    session.add(row)
    await session.flush()
    return row


def _service(session, org_id, storage, embeddings, llm) -> BrandDocumentService:
    return BrandDocumentService(session, org_id, storage=storage, embeddings=embeddings, llm=llm)


async def _ingest(
    session, org, brand, storage, embeddings, llm, text=GUIDELINES, title="Guidelines"
):
    service = _service(session, org.id, storage, embeddings, llm)
    row = await service.create_text_document(brand_id=brand.id, title=title, content=text)
    status = await service.process(row.id)
    await session.refresh(row)
    return row, status


class TestIngestPipeline:
    async def test_a_text_document_runs_to_completed(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        row, status = await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        assert status is DocumentStatus.COMPLETED
        assert row.status == DocumentStatus.COMPLETED.value
        assert row.chunk_count > 0
        assert row.error is None

    async def test_chunks_land_in_pgvector_with_embeddings(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        repo = BrandChunkRepository(session, workspace.org.id)
        assert await repo.count_for_brand(brand.id) > 0

        from sqlalchemy import select

        chunk = (
            (
                await session.execute(
                    select(BrandChunkRow).where(BrandChunkRow.brand_profile_id == brand.id)
                )
            )
            .scalars()
            .first()
        )
        assert chunk is not None
        assert chunk.embedding is not None
        assert len(chunk.embedding) == 1536

    async def test_the_file_is_persisted_through_the_storage_provider(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        row, _ = await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        assert row.storage_key is not None
        assert b"Northline" in await storage.get(row.storage_key)

    async def test_a_pdf_is_extracted_and_keeps_page_numbers(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        import fitz

        document = fitz.open()
        for body in ("Our tone of voice is confident.", "We never claim indestructible."):
            document.new_page().insert_text((72, 96), body, fontsize=11)
        data = document.tobytes()
        document.close()

        from app.services.uploads import validate_upload

        upload = validate_upload(
            data,
            declared_mime="application/pdf",
            filename="guide.pdf",
            allowed=frozenset({"application/pdf"}),
            max_bytes=15 * 1024 * 1024,
        )
        brand = await _brand(session, workspace.org)
        service = _service(session, workspace.org.id, storage, embeddings, llm)
        row = await service.upload(brand_id=brand.id, upload=upload, title="Guide")
        assert await service.process(row.id) is DocumentStatus.COMPLETED

        await session.refresh(row)
        assert row.page_count == 2
        from sqlalchemy import select

        pages = (
            (
                await session.execute(
                    select(BrandChunkRow.page).where(BrandChunkRow.brand_document_id == row.id)
                )
            )
            .scalars()
            .all()
        )
        assert set(pages) == {1, 2}

    async def test_reprocessing_replaces_chunks_rather_than_duplicating(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        row, _ = await _ingest(session, workspace.org, brand, storage, embeddings, llm)
        repo = BrandChunkRepository(session, workspace.org.id)
        first = await repo.count_for_brand(brand.id)

        service = _service(session, workspace.org.id, storage, embeddings, llm)
        await service.process(row.id)

        assert await repo.count_for_brand(brand.id) == first

    async def test_an_identical_reupload_is_deduplicated(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        """Re-embedding unchanged bytes is wasted provider spend (§17)."""
        brand = await _brand(session, workspace.org)
        row, _ = await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        from app.services.uploads import validate_upload

        upload = validate_upload(
            GUIDELINES.encode(),
            declared_mime="text/plain",
            filename="g.txt",
            allowed=frozenset({"text/plain"}),
            max_bytes=15 * 1024 * 1024,
        )
        service = _service(session, workspace.org.id, storage, embeddings, llm)
        again = await service.upload(brand_id=brand.id, upload=upload, title="Same")
        assert again.id == row.id


class TestFailureRepresentation:
    async def test_an_empty_document_fails_at_extraction_and_says_so(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        service = _service(session, workspace.org.id, storage, embeddings, llm)
        row = await service.create_text_document(
            brand_id=brand.id, title="Blank", content="    \n\n   "
        )
        status = await service.process(row.id)

        await session.refresh(row)
        assert status is DocumentStatus.EXTRACTION_FAILED
        assert row.status == DocumentStatus.EXTRACTION_FAILED.value
        assert row.error and "no readable text" in row.error.lower()
        assert row.chunk_count == 0

    async def test_an_embedding_failure_is_not_reported_as_completed(
        self, session, workspace, storage, llm
    ) -> None:
        """A stage that failed must never leave the document at COMPLETED."""
        brand = await _brand(session, workspace.org)
        failing = MockEmbeddingProvider(failure_mode="timeout")
        service = _service(session, workspace.org.id, storage, failing, llm)
        row = await service.create_text_document(
            brand_id=brand.id, title="Guidelines", content=GUIDELINES
        )
        status = await service.process(row.id)

        await session.refresh(row)
        assert status is DocumentStatus.EMBEDDING_FAILED
        assert row.error is not None
        assert "timeout" not in row.error.lower()  # no raw provider wording
        assert await BrandChunkRepository(session, workspace.org.id).count_for_brand(brand.id) == 0

    async def test_an_analysis_failure_still_leaves_knowledge_searchable(
        self, session, workspace, storage, embeddings
    ) -> None:
        """Facts are a bonus; losing them must not discard the embeddings."""
        brand = await _brand(session, workspace.org)
        service = _service(
            session,
            workspace.org.id,
            storage,
            embeddings,
            MockLLMProvider(failure_mode="malformed"),
        )
        row = await service.create_text_document(
            brand_id=brand.id, title="Guidelines", content=GUIDELINES
        )
        status = await service.process(row.id)

        assert status is DocumentStatus.COMPLETED
        assert await BrandChunkRepository(session, workspace.org.id).count_for_brand(brand.id) > 0

    async def test_a_corrupt_pdf_fails_without_leaking_the_library_error(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        from app.services.uploads import validate_upload

        upload = validate_upload(
            b"%PDF-1.7 not actually a pdf",
            declared_mime="application/pdf",
            filename="broken.pdf",
            allowed=frozenset({"application/pdf"}),
            max_bytes=15 * 1024 * 1024,
        )
        brand = await _brand(session, workspace.org)
        service = _service(session, workspace.org.id, storage, embeddings, llm)
        row = await service.upload(brand_id=brand.id, upload=upload, title="Broken")

        assert await service.process(row.id) is DocumentStatus.EXTRACTION_FAILED
        await session.refresh(row)
        assert "fitz" not in (row.error or "").lower()
        assert "traceback" not in (row.error or "").lower()


class TestRetrieval:
    async def test_retrieval_ranks_the_relevant_passage_first(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        hits = await retriever.retrieve(
            brand_id=brand.id, query="what claims are prohibited indestructible", top_k=3
        )
        assert hits
        assert "indestructible" in hits[0].content.lower()
        assert hits[0].score > 0

    async def test_hits_carry_their_source_metadata(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        row, _ = await _ingest(session, workspace.org, brand, storage, embeddings, llm)

        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        hit = (await retriever.retrieve(brand_id=brand.id, query="logo clear space"))[0]
        assert hit.document_id == str(row.id)
        assert hit.document_title == "Guidelines"
        assert hit.chunk_id

    async def test_top_k_is_respected(self, session, workspace, storage, embeddings, llm) -> None:
        brand = await _brand(session, workspace.org)
        await _ingest(session, workspace.org, brand, storage, embeddings, llm)
        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        assert len(await retriever.retrieve(brand_id=brand.id, query="brand", top_k=1)) == 1

    async def test_an_empty_query_returns_nothing_rather_than_everything(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        brand = await _brand(session, workspace.org)
        await _ingest(session, workspace.org, brand, storage, embeddings, llm)
        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        assert await retriever.retrieve(brand_id=brand.id, query="   ") == []

    async def test_it_returns_the_domain_shape_campaign_nodes_will_consume(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        """Milestone 4 reads `BrandKnowledge` from state; returning that type
        here is what lets it consume this without an adapter."""
        brand = await _brand(session, workspace.org)
        await _ingest(session, workspace.org, brand, storage, embeddings, llm)
        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)

        knowledge = await retriever.as_brand_knowledge(brand_id=brand.id, query="tone of voice")
        assert knowledge.query == "tone of voice"
        assert knowledge.chunks
        assert "confident" in knowledge.as_context().lower()


class TestKnowledgeTenancy:
    """Mandatory per the Milestone 2 brief: this is a new attack surface."""

    async def test_organization_a_cannot_retrieve_organization_b_knowledge(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        await _ingest(session, theirs, their_brand, storage, embeddings, llm)

        # The attacker knows the brand id and asks the right question.
        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        hits = await retriever.retrieve(
            brand_id=their_brand.id, query="prohibited claims indestructible", top_k=10
        )
        assert hits == []

    async def test_a_second_brand_in_the_same_organization_is_also_isolated(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        """An agency holding competing clients needs brand-level separation,
        not only organization-level."""
        first = await _brand(session, workspace.org, name="Brand One")
        second = await _brand(session, workspace.org, name="Brand Two")
        await _ingest(session, workspace.org, first, storage, embeddings, llm)
        await _ingest(
            session,
            workspace.org,
            second,
            storage,
            embeddings,
            llm,
            text=LOGO_ONLY,
            title="Other brand rules",
        )

        retriever = BrandKnowledgeRetriever(session, workspace.org.id, embeddings=embeddings)
        hits = await retriever.retrieve(brand_id=second.id, query="indestructible", top_k=10)
        assert all("indestructible" not in h.content.lower() for h in hits)

    async def test_chunk_counts_do_not_leak_across_organizations(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        await _ingest(session, theirs, their_brand, storage, embeddings, llm)

        repo = BrandChunkRepository(session, workspace.org.id)
        assert await repo.count_for_brand(their_brand.id) == 0

    async def test_processing_another_organizations_document_does_nothing(
        self, session, workspace, storage, embeddings, llm
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        service = _service(session, theirs.id, storage, embeddings, llm)
        their_doc = await service.create_text_document(
            brand_id=their_brand.id, title="Theirs", content=GUIDELINES
        )

        attacker = _service(session, workspace.org.id, storage, embeddings, llm)
        await attacker.process(their_doc.id)

        await session.refresh(their_doc)
        assert their_doc.status == DocumentStatus.PENDING.value
        assert (
            await BrandChunkRepository(session, workspace.org.id).count_for_brand(their_brand.id)
            == 0
        )
