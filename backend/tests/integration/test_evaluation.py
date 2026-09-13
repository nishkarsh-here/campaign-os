"""Evaluation orchestration: batches, partial failure, selection, tenancy.

Exercised at the service level with the test session, because that is the real
code path — the API only schedules it. Nothing here reaches a live provider:
failures use the mock LLM's own failure modes, so the FAILED and partial-success
paths are real rather than simulated.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import Settings, get_settings
from app.db.models import (
    BrandProfileRow,
    CampaignRow,
    CampaignSpecificationRow,
    CanonicalPromptRow,
    CreativeSpecificationRow,
    GeneratedAssetRow,
    GenerationJobRow,
    ModelPromptRow,
)
from app.domain.common import Channel, JobStatus, Role, utc_now
from app.domain.creative import CreativeSpecification
from app.domain.evaluation import EVALUATOR_VERSION, Disposition
from app.domain.workspace import Principal, User
from app.errors import Conflict, NotFound
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.image import MockImageProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.evaluation import (
    CreativeEvaluationRepository,
    CreativeSelectionRepository,
)
from app.services.evaluation_stage import EvaluationService
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration


def _settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update({"image_provider": "mock", "image_providers": "", "mock_failure_mode": "none"})
    base.update(overrides)
    return Settings(**base)


def _principal(workspace) -> Principal:
    return Principal(
        user=User(id=str(workspace.user.id), email=workspace.user.email),
        organization_id=str(workspace.org.id),
        role=Role.ADMIN,
    )


def _specification(campaign_id: uuid.UUID, version: int = 2) -> CreativeSpecification:
    return CreativeSpecification(
        campaign_id=str(campaign_id),
        direction_id=str(uuid.uuid4()),
        version=version,
        concept="The facade, read as engineering",
        visual_story="A single bay at the hour the light rakes across it",
        emotional_angle="engineering confidence",
        headline="Built to outlast the building it clads",
        cta="Request the specification pack",
        visual_metaphor="machined precision standing for permanence",
        composition="tight orthographic framing",
        focal_point="the joint between two panels",
        subject="a single bay of the FS-9 facade system",
        environment="a fabrication floor",
        lighting="hard directional studio light",
        palette=["#1F2933", "#E4572E"],
        product_integration="the system is the subject",
        brand_integration="colour and restraint, not a badge",
    )


async def _campaign_with_assets(
    session, org, storage, *, count: int = 3, version: int = 2
) -> tuple[CampaignRow, list[GeneratedAssetRow]]:
    """A campaign whose approved plan produced `count` real stored plates.

    The plates are genuine PNGs from the mock image provider, so evaluation
    reads real bytes and the mock evaluator scores them from real pixels.
    """
    brand = BrandProfileRow(
        organization_id=org.id,
        name=f"Northline {uuid.uuid4().hex[:6]}",
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": "Northline",
            "prohibited_claims": ["indestructible"],
        },
    )
    session.add(brand)
    await session.flush()

    campaign_id = uuid.uuid4()
    campaign = CampaignRow(
        id=campaign_id,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title="FS-9 launch",
        status="SPECIFICATION_CONFIRMED",
        thread_id=str(campaign_id),
        draft_inputs={},
    )
    session.add(campaign)
    await session.flush()

    specification = _specification(campaign_id, version)
    session.add(
        CreativeSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            direction_id=uuid.UUID(specification.direction_id),
            version=version,
            payload=specification.model_dump(mode="json"),
            approved_at=utc_now(),
        )
    )
    session.add(
        CampaignSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            version=1,
            schema_version=1,
            payload={
                "campaign_id": str(campaign_id),
                "title": "Launch",
                "objective": "Get FS-9 onto shortlists at design stage",
                "audience": "Architects and facade consultants in Mumbai",
                "product": "FS-9 facade system",
                "key_message": "Built to outlast the building it clads",
                "cta": "Request the specification pack",
                "channels": [Channel.INSTAGRAM_POST.value],
                "region": "Maharashtra, India",
            },
        )
    )
    # The real chain: canonical prompt -> model prompt -> job -> asset. The
    # foreign keys are genuine, so a fixture that invented ids would be testing
    # a shape the database does not allow.
    canonical = CanonicalPromptRow(
        organization_id=org.id,
        campaign_id=campaign_id,
        specification_id=uuid.UUID(specification.id),
        specification_version=version,
        version=1,
        payload={"subject": specification.subject},
        source_fingerprint=uuid.uuid4().hex,
    )
    session.add(canonical)
    await session.flush()

    model_prompt = ModelPromptRow(
        organization_id=org.id,
        campaign_id=campaign_id,
        canonical_prompt_id=canonical.id,
        provider="mock",
        model="mock-image-1",
        version=1,
        payload={"text": "a plate"},
    )
    session.add(model_prompt)
    await session.flush()

    job = GenerationJobRow(
        organization_id=org.id,
        campaign_id=campaign_id,
        model_prompt_id=model_prompt.id,
        specification_id=uuid.UUID(specification.id),
        specification_version=version,
        batch_id=uuid.uuid4(),
        provider="mock",
        model="mock-image-1",
        status=JobStatus.COMPLETED.value,
        idempotency_key=f"key-{uuid.uuid4()}",
    )
    session.add(job)
    await session.flush()

    from app.providers.base import ImageRequest

    provider = MockImageProvider()
    assets: list[GeneratedAssetRow] = []
    for index in range(count):
        (image,) = await provider.generate(
            ImageRequest(prompt=f"plate {index} for {campaign_id}", aspect_ratio="1:1")
        )
        key = f"org-{org.id}/campaign-{campaign_id}/generated/{uuid.uuid4().hex}.png"
        await storage.put(key, image.data, mime_type="image/png")
        row = GeneratedAssetRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            generation_job_id=job.id,
            model_prompt_id=job.model_prompt_id,
            specification_id=uuid.UUID(specification.id),
            specification_version=version,
            provider="mock",
            model="mock-image-1",
            kind="VISUAL_PLATE",
            storage_key=key,
            mime_type="image/png",
            width=image.width,
            height=image.height,
            meta={},
        )
        session.add(row)
        assets.append(row)
    await session.flush()
    return campaign, assets


def _service(session, workspace, storage, **overrides) -> EvaluationService:
    return EvaluationService(
        session,
        _principal(workspace),
        settings=_settings(**overrides),
        storage=storage,
        llm=MockLLMProvider(overrides.get("mock_failure_mode", "none")),
        embeddings=MockEmbeddingProvider(),
    )


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path))


class TestEvaluatingABatch:
    async def test_starting_claims_a_pending_evaluation_per_asset(
        self, session, workspace, storage
    ) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)

        view, claimed = await service.start(campaign.id)
        assert len(claimed) == len(assets)
        assert view.in_flight == len(assets)
        assert view.summary.ranked == []

    async def test_running_evaluates_every_asset(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        view = await service.current(campaign.id)
        assert len(view.summary.ranked) == len(assets)
        assert view.in_flight == 0
        assert view.summary.failed_asset_ids == []
        assert view.summary.outcome() == f"All {len(assets)} assets evaluated."

    async def test_each_evaluation_is_scored_and_disposed(
        self, session, workspace, storage
    ) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        view = await service.current(campaign.id)
        for row in view.summary.ranked:
            assert 0 <= row.overall_score <= 100
            assert row.disposition in set(Disposition)
            assert row.reason

    async def test_assets_score_differently(self, session, workspace, storage) -> None:
        """Ranking is only meaningful if the evaluator discriminates."""
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=4)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        view = await service.current(campaign.id)
        scores = {row.overall_score for row in view.summary.ranked}
        assert len(scores) >= 2

    async def test_the_ranking_is_ordered_and_numbered(self, session, workspace, storage) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=4)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        ranked = (await service.current(campaign.id)).summary.ranked
        assert [row.rank for row in ranked] == list(range(1, len(ranked) + 1))
        scores = [row.overall_score for row in ranked]
        assert scores == sorted(scores, reverse=True)

    async def test_a_recommendation_is_produced(self, session, workspace, storage) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=4)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        recommendation = (await service.current(campaign.id)).summary.recommendation
        assert recommendation is not None
        assert recommendation.reason

    async def test_the_evaluation_records_its_source_plan(
        self, session, workspace, storage
    ) -> None:
        """Provenance for Milestone 8: judged against version 2, not "latest"."""
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, version=2)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert rows
        for row in rows:
            assert row.specification_version == 2
            assert row.evaluator_version == EVALUATOR_VERSION
            assert row.payload is not None
            assert row.payload["specification_version"] == 2

    async def test_starting_twice_does_not_double_evaluate(
        self, session, workspace, storage
    ) -> None:
        """Same asset, same evaluator version: one row, reset — never a second
        opinion produced from identical criteria."""
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.start(campaign.id)
        await service.start(campaign.id)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert len(rows) == len(assets)

    async def test_evaluating_without_assets_is_a_conflict(
        self, session, workspace, storage
    ) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=0)
        service = _service(session, workspace, storage)

        view = await service.current(campaign.id)
        assert view.can_evaluate is False
        assert view.blocked_reason and "Generate creatives" in view.blocked_reason

        with pytest.raises(Conflict):
            await service.start(campaign.id)

    async def test_a_subset_of_assets_can_be_evaluated(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=3)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id, asset_ids=[assets[0].id])
        assert len(claimed) == 1

    async def test_an_unknown_asset_id_is_not_found(self, session, workspace, storage) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).start(campaign.id, asset_ids=[uuid.uuid4()])


class TestPartialFailure:
    async def test_a_provider_failure_fails_only_its_own_asset(
        self, session, workspace, storage
    ) -> None:
        """Seven of eight is seven usable evaluations, not a wasted batch."""
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=3)
        working = _service(session, workspace, storage)
        _, claimed = await working.start(campaign.id)

        # One asset is evaluated by a provider that times out; the rest work.
        broken = _service(session, workspace, storage, mock_failure_mode="timeout")
        await broken.run_one(claimed[0])
        await working.run_evaluations(claimed[1:])

        view = await working.current(campaign.id)
        assert len(view.summary.ranked) == 2
        assert len(view.summary.failed_asset_ids) == 1
        assert view.summary.outcome() == "2/3 assets evaluated — 1 failed."
        assert view.summary.recommendation is not None
        assert view.summary.recommendation.generated_asset_id is not None

    async def test_a_failure_records_a_readable_reason(self, session, workspace, storage) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=1)
        service = _service(session, workspace, storage, mock_failure_mode="rate_limit")
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        (row,) = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert row.status == JobStatus.FAILED.value
        assert row.error is not None
        assert "rate limit" in str(row.error["message"]).lower()
        assert row.payload is None
        assert row.overall_score is None

    async def test_an_unevaluable_asset_fails_without_a_model_call(
        self, session, workspace, storage
    ) -> None:
        """A deterministic pre-check must not cost a provider call."""
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=1)
        assets[0].width = 32
        assets[0].height = 32
        await session.flush()

        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        (row,) = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert row.status == JobStatus.FAILED.value
        assert row.error is not None
        assert row.error["code"] == "ASSET_NOT_EVALUABLE"

    async def test_a_missing_image_fails_cleanly(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=1)
        assets[0].storage_key = "org-x/campaign-y/generated/gone.png"
        await session.flush()

        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        (row,) = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert row.status == JobStatus.FAILED.value
        assert row.error is not None
        assert row.error["code"] == "ASSET_UNREADABLE"

    async def test_no_evaluation_is_left_running(self, session, workspace, storage) -> None:
        """The UI must never show a card that spins forever."""
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=2)
        service = _service(session, workspace, storage, mock_failure_mode="unavailable")
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert all(row.status == JobStatus.FAILED.value for row in rows)
        assert (await service.current(campaign.id)).in_flight == 0


class TestRetry:
    async def test_a_failed_evaluation_can_be_retried_and_succeed(
        self, session, workspace, storage
    ) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=1)
        failing = _service(session, workspace, storage, mock_failure_mode="timeout")
        _, claimed = await failing.start(campaign.id)
        await failing.run_evaluations(claimed)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        assert rows[0].status == JobStatus.FAILED.value

        working = _service(session, workspace, storage)
        retried = await working.retry(campaign.id, rows[0].id)
        await working.run_evaluations([retried])

        view = await working.current(campaign.id)
        assert len(view.summary.ranked) == 1
        assert view.summary.failed_asset_ids == []

    async def test_a_completed_evaluation_cannot_be_retried(
        self, session, workspace, storage
    ) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=1)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        with pytest.raises(Conflict):
            await service.retry(campaign.id, rows[0].id)

    async def test_an_unknown_evaluation_cannot_be_retried(
        self, session, workspace, storage
    ) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).retry(campaign.id, uuid.uuid4())


class TestSelection:
    async def test_a_human_can_select_an_asset(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        view = await service.select(campaign.id, assets[1].id, note="Best light.")
        assert view.summary.selected_asset_id == str(assets[1].id)

    async def test_the_selection_persists(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.select(campaign.id, assets[0].id)

        again = await _service(session, workspace, storage).current(campaign.id)
        assert again.summary.selected_asset_id == str(assets[0].id)

    async def test_a_human_may_overrule_the_recommendation(
        self, session, workspace, storage
    ) -> None:
        """The ranking is advice. The person decides."""
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage, count=3)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)

        view = await service.current(campaign.id)
        recommended = view.summary.recommendation
        assert recommended is not None
        bottom = view.summary.ranked[-1].generated_asset_id
        assert bottom != recommended.generated_asset_id

        after = await service.select(campaign.id, uuid.UUID(bottom))
        assert after.summary.selected_asset_id == bottom

    async def test_changing_the_choice_keeps_the_history(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.select(campaign.id, assets[0].id)
        await service.select(campaign.id, assets[1].id)

        history = await CreativeSelectionRepository(session, workspace.org.id).history(campaign.id)
        assert [str(row.generated_asset_id) for row in history] == [
            str(assets[0].id),
            str(assets[1].id),
        ]

    async def test_a_selection_records_who_and_why(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start(campaign.id)
        await service.run_evaluations(claimed)
        await service.select(campaign.id, assets[0].id, note="Client liked this one.")

        row = await CreativeSelectionRepository(session, workspace.org.id).current(campaign.id)
        assert row is not None
        assert row.selected_by == workspace.user.id
        assert row.note == "Client liked this one."
        # The evaluation that was on the table when they chose.
        assert row.evaluation_id is not None

    async def test_an_unevaluated_asset_can_still_be_selected(
        self, session, workspace, storage
    ) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage)
        view = await _service(session, workspace, storage).select(campaign.id, assets[0].id)
        assert view.summary.selected_asset_id == str(assets[0].id)

    async def test_an_unknown_asset_cannot_be_selected(self, session, workspace, storage) -> None:
        campaign, _ = await _campaign_with_assets(session, workspace.org, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).select(campaign.id, uuid.uuid4())


class TestTenancy:
    async def _their_campaign(self, session, storage):
        theirs = await make_org(session)
        campaign, assets = await _campaign_with_assets(session, theirs, storage)
        return theirs, campaign, assets

    async def test_another_organizations_campaign_cannot_be_evaluated(
        self, session, workspace, storage
    ) -> None:
        _, campaign, _ = await self._their_campaign(session, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).start(campaign.id)

    async def test_another_organizations_evaluation_state_is_invisible(
        self, session, workspace, storage
    ) -> None:
        _, campaign, _ = await self._their_campaign(session, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).current(campaign.id)

    async def test_another_organizations_evaluations_are_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs, campaign, _ = await self._their_campaign(session, storage)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage)
        _, claimed = await their_service.start(campaign.id)
        await their_service.run_evaluations(claimed)

        mine = CreativeEvaluationRepository(session, workspace.org.id)
        assert await mine.for_campaign(campaign.id) == []
        assert await mine.get(claimed[0]) is None

    async def test_another_organizations_asset_cannot_be_selected(
        self, session, workspace, storage
    ) -> None:
        theirs, their_campaign, their_assets = await self._their_campaign(session, storage)
        mine, _ = await _campaign_with_assets(session, workspace.org, storage)

        service = _service(session, workspace, storage)
        # Neither through their campaign...
        with pytest.raises(NotFound):
            await service.select(their_campaign.id, their_assets[0].id)
        # ...nor by smuggling their asset id through mine.
        with pytest.raises(NotFound):
            await service.select(mine.id, their_assets[0].id)

    async def test_an_arbitrary_evaluation_id_cannot_be_retried_across_the_boundary(
        self, session, workspace, storage
    ) -> None:
        theirs, their_campaign, _ = await self._their_campaign(session, storage)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage, mock_failure_mode="timeout")
        _, claimed = await their_service.start(their_campaign.id)
        await their_service.run_evaluations(claimed)

        mine, _ = await _campaign_with_assets(session, workspace.org, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).retry(mine.id, claimed[0])

    async def test_an_asset_id_from_another_campaign_cannot_be_evaluated(
        self, session, workspace, storage
    ) -> None:
        """Both of my own campaigns: an asset id still cannot cross between
        them, because the filter is against *this* campaign's assets."""
        first, _ = await _campaign_with_assets(session, workspace.org, storage)
        _, other_assets = await _campaign_with_assets(session, workspace.org, storage)

        with pytest.raises(NotFound):
            await _service(session, workspace, storage).start(
                first.id, asset_ids=[other_assets[0].id]
            )

    async def test_the_evaluator_never_mixes_contexts(self, session, workspace, storage) -> None:
        """Two campaigns, two brands: each evaluation is judged against its own
        campaign's plan, never a neighbour's."""
        first, _ = await _campaign_with_assets(session, workspace.org, storage, count=1)
        second, _ = await _campaign_with_assets(session, workspace.org, storage, count=1)

        service = _service(session, workspace, storage)
        for campaign in (first, second):
            _, claimed = await service.start(campaign.id)
            await service.run_evaluations(claimed)

        repository = CreativeEvaluationRepository(session, workspace.org.id)
        for campaign in (first, second):
            rows = await repository.for_campaign(campaign.id)
            assert rows
            for row in rows:
                assert row.campaign_id == campaign.id
                assert row.payload is not None
                assert row.payload["campaign_id"] == str(campaign.id)


class TestDatabaseConstraints:
    async def test_an_unknown_disposition_is_rejected(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=1)
        from sqlalchemy import text

        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "insert into creative_evaluations (organization_id, campaign_id, "
                    "generated_asset_id, specification_id, specification_version, "
                    "evaluator_version, status, disposition) values "
                    "(:org, :camp, :asset, :spec, 1, 'v1', 'COMPLETED', 'MAYBE')"
                ),
                {
                    "org": workspace.org.id,
                    "camp": campaign.id,
                    "asset": assets[0].id,
                    "spec": uuid.uuid4(),
                },
            )
        assert "disposition_valid" in str(caught.value)
        await savepoint.rollback()

    async def test_a_score_outside_the_scale_is_rejected(self, session, workspace, storage) -> None:
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=1)
        from sqlalchemy import text

        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "insert into creative_evaluations (organization_id, campaign_id, "
                    "generated_asset_id, specification_id, specification_version, "
                    "evaluator_version, status, overall_score) values "
                    "(:org, :camp, :asset, :spec, 1, 'v1', 'COMPLETED', 140)"
                ),
                {
                    "org": workspace.org.id,
                    "camp": campaign.id,
                    "asset": assets[0].id,
                    "spec": uuid.uuid4(),
                },
            )
        assert "score_range_valid" in str(caught.value)
        await savepoint.rollback()

    async def test_one_evaluation_per_asset_and_version(self, session, workspace, storage) -> None:
        """The uniqueness that makes re-evaluation idempotent."""
        campaign, assets = await _campaign_with_assets(session, workspace.org, storage, count=1)
        repository = CreativeEvaluationRepository(session, workspace.org.id)
        await repository.claim(
            campaign_id=campaign.id,
            generated_asset_id=assets[0].id,
            specification_id=uuid.uuid4(),
            specification_version=1,
            evaluator_version="v1",
        )

        from app.db.models import CreativeEvaluationRow

        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            session.add(
                CreativeEvaluationRow(
                    organization_id=workspace.org.id,
                    campaign_id=campaign.id,
                    generated_asset_id=assets[0].id,
                    specification_id=uuid.uuid4(),
                    specification_version=1,
                    evaluator_version="v1",
                    status="PENDING",
                )
            )
            await session.flush()
        assert "generated_asset_id" in str(caught.value)
        await savepoint.rollback()
