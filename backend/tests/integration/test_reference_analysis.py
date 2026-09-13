"""Reference analysis persistence, failure states, and tenancy.

A campaign reference carries a competitor's creative inspiration and, through
the Creative Context, a brand's confidential guardrails — so cross-organization
access is the primary risk here.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models import BrandProfileRow, CampaignReferenceRow, CampaignRow
from app.domain.common import StyleFamily
from app.domain.reference import CreativePreferences, ReferenceAnalysis, ReferenceStatus
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.campaigns import CampaignReferenceRepository
from app.services.creative_context import CreativeContextService, build_preferences
from app.services.reference_intelligence import ReferenceIntelligenceService
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "store"))


async def _brand(session, org, name: str = "Northline") -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": name,
            "positioning": "Engineered facade systems",
            "prohibited_claims": ["indestructible"],
            "colors": [{"name": "Graphite", "hex": "#1F2933", "role": "primary"}],
            "voice": {
                "tone_attributes": ["confident"],
                "person": None,
                "writing_rules": [],
                "avoid": [],
            },
        },
    )
    session.add(row)
    await session.flush()
    return row


async def _campaign(session, org, brand) -> CampaignRow:
    cid = uuid.uuid4()
    row = CampaignRow(
        id=cid,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title="Launch",
        status="DRAFT",
        thread_id=str(cid),
        draft_inputs={},
        creative_preferences={},
    )
    session.add(row)
    await session.flush()
    return row


async def _reference(session, org, campaign, storage, data: bytes = PNG) -> CampaignReferenceRow:
    key = f"org-{org.id}/brand-{campaign.id}/references/{uuid.uuid4().hex}.png"
    await storage.put(key, data, mime_type="image/png")
    return await CampaignReferenceRepository(session, org.id).create(
        campaign_id=campaign.id,
        storage_key=key,
        filename="poster.png",
        mime_type="image/png",
        size_bytes=len(data),
        note="I like the restraint",
    )


def _service(session, org_id, storage, llm=None) -> ReferenceIntelligenceService:
    return ReferenceIntelligenceService(
        session, org_id, storage=storage, llm=llm or MockLLMProvider()
    )


class TestAnalysisLifecycle:
    async def test_a_reference_starts_pending(self, session, workspace, storage) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)
        assert row.status == ReferenceStatus.PENDING.value
        assert row.analysis is None

    async def test_analysis_completes_and_persists_typed_output(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)

        analysed = await _service(session, workspace.org.id, storage).analyze(row.id)

        assert analysed is not None
        assert analysed.status == ReferenceStatus.COMPLETED.value
        assert analysed.analyzed_at is not None
        assert analysed.error is None
        # Validated on read: the stored payload really is a ReferenceAnalysis.
        parsed = ReferenceAnalysis.model_validate(analysed.analysis)
        assert parsed.reference_id == str(row.id)
        assert parsed.style_families and parsed.style_takeaways

    async def test_the_analysis_states_what_it_will_not_reuse(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)
        analysed = await _service(session, workspace.org.id, storage).analyze(row.id)

        parsed = ReferenceAnalysis.model_validate(analysed.analysis)
        assert parsed.not_transferable, "the IP boundary must be visible to the user"

    async def test_an_already_analysed_reference_is_not_reanalysed(
        self, session, workspace, storage
    ) -> None:
        """Re-analysing costs a multimodal call for no new information (§17)."""
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)
        service = _service(session, workspace.org.id, storage)

        first = await service.analyze(row.id)
        stamp = first.analyzed_at
        again = await service.analyze(row.id)
        assert again.analyzed_at == stamp

    async def test_force_reanalyses(self, session, workspace, storage) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)
        service = _service(session, workspace.org.id, storage)

        await service.analyze(row.id)
        forced = await service.analyze(row.id, force=True)
        assert forced.status == ReferenceStatus.COMPLETED.value


class TestFailureStates:
    async def test_a_provider_failure_is_recorded_not_reported_as_success(
        self, session, workspace, storage
    ) -> None:
        """A failed analysis must never leave the reference looking analysed."""
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)

        failing = MockLLMProvider(failure_mode="malformed")
        result = await _service(session, workspace.org.id, storage, failing).analyze(row.id)

        assert result.status == ReferenceStatus.FAILED.value
        assert result.analysis is None
        assert result.error

    async def test_the_error_message_does_not_leak_the_provider_exception(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)

        failing = MockLLMProvider(failure_mode="timeout")
        result = await _service(session, workspace.org.id, storage, failing).analyze(row.id)

        lowered = (result.error or "").lower()
        assert "traceback" not in lowered
        assert "providertimeout" not in lowered

    async def test_a_retry_after_failure_clears_the_error(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await _reference(session, workspace.org, campaign, storage)

        await _service(
            session, workspace.org.id, storage, MockLLMProvider(failure_mode="timeout")
        ).analyze(row.id)
        recovered = await _service(session, workspace.org.id, storage).analyze(row.id, force=True)
        assert recovered.status == ReferenceStatus.COMPLETED.value
        assert recovered.error is None

    async def test_missing_stored_bytes_fail_cleanly(self, session, workspace, storage) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        row = await CampaignReferenceRepository(session, workspace.org.id).create(
            campaign_id=campaign.id,
            storage_key="org-x/brand-y/references/missing.png",
            filename="missing.png",
            mime_type="image/png",
            size_bytes=1,
        )
        result = await _service(session, workspace.org.id, storage).analyze(row.id)
        assert result.status == ReferenceStatus.FAILED.value


class TestReferenceTenancy:
    """Mandatory per the Milestone 4 brief."""

    async def test_another_organizations_reference_cannot_be_read(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        their_ref = await _reference(session, theirs, their_campaign, storage)

        repo = CampaignReferenceRepository(session, workspace.org.id)
        assert await repo.get(their_ref.id) is None

    async def test_another_organizations_reference_cannot_be_analyzed(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        their_ref = await _reference(session, theirs, their_campaign, storage)

        # The attacker's organization scope finds nothing to analyse.
        assert await _service(session, workspace.org.id, storage).analyze(their_ref.id) is None

        await session.refresh(their_ref)
        assert their_ref.status == ReferenceStatus.PENDING.value

    async def test_listing_never_crosses_organizations(self, session, workspace, storage) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        await _reference(session, theirs, their_campaign, storage)

        repo = CampaignReferenceRepository(session, workspace.org.id)
        assert await repo.list_for_campaign(their_campaign.id) == []

    async def test_analyses_for_another_organizations_campaign_are_empty(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        their_ref = await _reference(session, theirs, their_campaign, storage)
        await _service(session, theirs.id, storage).analyze(their_ref.id)

        mine = _service(session, workspace.org.id, storage)
        assert await mine.analyses_for_campaign(their_campaign.id) == []
        assert (await mine.aggregate_for_campaign(their_campaign.id)).reference_count == 0


class TestCreativeContext:
    def _context_service(self, session, org_id, storage) -> CreativeContextService:
        return CreativeContextService(
            session,
            org_id,
            storage=storage,
            llm=MockLLMProvider(),
            embeddings=MockEmbeddingProvider(),
        )

    async def test_it_combines_all_four_sources(self, session, workspace, storage) -> None:
        from app.repositories.campaigns import CampaignSpecificationRepository

        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        reference = await _reference(session, workspace.org, campaign, storage)
        await _service(session, workspace.org.id, storage).analyze(reference.id)

        await CampaignSpecificationRepository(session, workspace.org.id).create_version(
            campaign_id=campaign.id,
            payload={
                "campaign_id": str(campaign.id),
                "title": "Launch",
                "objective": "Establish the premium specification choice",
                "audience": "Architects in Maharashtra",
                "product": "FS-9",
                "key_message": "Engineered to outlast",
                "cta": "Request a pack",
                "channels": ["linkedin"],
            },
        )
        campaign.creative_preferences = build_preferences(
            selected_styles=[StyleFamily.PREMIUM], reference_styles=[]
        ).model_dump(mode="json")
        await session.flush()

        context = await self._context_service(session, workspace.org.id, storage).build(campaign)

        # 1. Campaign Specification
        assert context.specification is not None
        assert context.specification.product == "FS-9"
        # 2. Brand Brain
        assert context.brand_name == "Northline"
        assert "indestructible" in context.guardrails.prohibited_claims
        assert "#1F2933" in context.guardrails.palette
        # 3. Reference style DNA
        assert context.reference_style.reference_count == 1
        assert context.reference_analyses
        # 4. Preferences
        assert StyleFamily.PREMIUM in context.preferences.selected_styles
        assert context.style_profile.weights
        assert context.is_ready()

    async def test_missing_pieces_are_named_as_gaps_not_invented(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)

        context = await self._context_service(session, workspace.org.id, storage).build(campaign)

        assert context.is_ready() is False
        joined = " ".join(context.gaps).lower()
        assert "specification" in joined
        assert "reference" in joined

    async def test_the_summary_reads_as_a_direction(self, session, workspace, storage) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        campaign.creative_preferences = build_preferences(
            selected_styles=[StyleFamily.PREMIUM], reference_styles=[]
        ).model_dump(mode="json")
        await session.flush()

        context = await self._context_service(session, workspace.org.id, storage).build(campaign)
        summary = context.summarise()
        assert "Northline" in summary
        assert "premium" in summary.lower()

    async def test_preferences_reweight_when_a_reference_is_added(
        self, session, workspace, storage
    ) -> None:
        """Adding inspiration should shift the profile without the user
        re-picking anything."""
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        service = self._context_service(session, workspace.org.id, storage)
        await service.save_preferences(
            campaign,
            CreativePreferences(selected_styles=[StyleFamily.PREMIUM]),
        )
        before = (await service.preferences_for(campaign)).style_profile.weights

        reference = await _reference(session, workspace.org, campaign, storage)
        await _service(session, workspace.org.id, storage).analyze(reference.id)
        after = (await service.preferences_for(campaign)).style_profile.weights

        assert after != before
        assert "premium" in after

    async def test_a_context_cannot_be_built_from_another_organizations_resources(
        self, session, workspace, storage
    ) -> None:
        """The scoped repositories make cross-tenant assembly impossible."""
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        their_ref = await _reference(session, theirs, their_campaign, storage)
        await _service(session, theirs.id, storage).analyze(their_ref.id)

        # Built with the attacker's scope against the victim's campaign row.
        context = await self._context_service(session, workspace.org.id, storage).build(
            their_campaign
        )

        assert context.brand_name is None
        assert context.guardrails.prohibited_claims == []
        assert context.reference_analyses == []
        assert context.specification is None
