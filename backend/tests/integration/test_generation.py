"""Generation: prompts, jobs, plates, and the boundaries around them.

The orchestration is exercised at the service level with the test session,
because that is the real code path — the API only schedules it. The HTTP layer
is covered for the things it actually owns: the approval gate, job creation,
retry rules, asset serving and tenancy.

Nothing here reaches a live provider. Failure cases use the mock's own failure
modes, so the FAILED and partial-success paths are real rather than simulated.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from app.config import Settings, get_settings
from app.db.models import BrandProfileRow, CampaignRow, CreativeSpecificationRow
from app.domain.common import JobStatus, Role, utc_now
from app.domain.creative import CreativeSpecification, NegativeConstraints
from app.domain.generation import AssetKind
from app.domain.workspace import Principal, User
from app.errors import Conflict, NotFound
from app.providers.base import GeneratedImage
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.generation import GeneratedAssetRepository, GenerationJobRepository
from app.services.generation import GenerationService, generated_asset_key
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration


def _settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(
        {
            "image_provider": "mock",
            "image_providers": "",
            "mock_failure_mode": "none",
            "mock_image_latency_seconds": 0.0,
        }
    )
    base.update(overrides)
    return Settings(**base)


def _principal(workspace) -> Principal:
    return Principal(
        user=User(id=str(workspace.user.id), email=workspace.user.email),
        organization_id=str(workspace.org.id),
        role=Role.ADMIN,
    )


async def _brand(session, org) -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=f"Northline {uuid.uuid4().hex[:6]}",
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": "Northline",
            "prohibited_claims": ["indestructible"],
        },
    )
    session.add(row)
    await session.flush()
    return row


async def _campaign_with_approved_specification(
    session, org, *, approved: bool = True
) -> CampaignRow:
    """A campaign carrying an approved Creative Specification — M6's entry."""
    brand = await _brand(session, org)
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

    specification = CreativeSpecification(
        campaign_id=str(campaign_id),
        direction_id=str(uuid.uuid4()),
        version=2,
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
        negative_constraints=NegativeConstraints(forbidden_elements=["stock-photo handshakes"]),
    )
    session.add(
        CreativeSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            direction_id=uuid.UUID(specification.direction_id),
            version=specification.version,
            payload=specification.model_dump(mode="json"),
            approved_at=utc_now() if approved else None,
        )
    )
    await session.flush()
    return campaign


def _service(session, workspace, storage, **settings_overrides) -> GenerationService:
    return GenerationService(
        session,
        _principal(workspace),
        settings=_settings(**settings_overrides),
        storage=storage,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
    )


class _JpegImageProvider:
    """Stands in for Gemini, which only ever returns JPEG. Deliberately not
    the mock provider: the mock renders PNG, so it cannot prove that the
    persistence path carries the provider's own format through."""

    name = "gemini"
    supported_aspect_ratios: tuple[str, ...] = ("1:1",)

    async def generate(self, request) -> list[GeneratedImage]:
        buffer = io.BytesIO()
        Image.new("RGB", (320, 320), (40, 60, 80)).save(buffer, format="JPEG")
        data = buffer.getvalue()
        return [
            GeneratedImage(
                data=data, mime_type="image/jpeg", width=320, height=320, seed=request.seed
            )
        ]

    async def health(self) -> bool:
        return True


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path))


# --------------------------------------------------------------- compilation
class TestCompilation:
    async def test_an_approved_specification_compiles(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        view = await _service(session, workspace, storage).compile_prompts(campaign.id)

        assert view.canonical_prompt is not None
        assert view.canonical_prompt.subject.startswith("a single bay")
        assert len(view.prompts) == 1
        assert view.prompts[0].provider == "mock"

    async def test_an_unapproved_specification_cannot_compile(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(
            session, workspace.org, approved=False
        )
        with pytest.raises(Conflict):
            await _service(session, workspace, storage).compile_prompts(campaign.id)

    async def test_compiling_twice_reuses_the_version(self, session, workspace, storage) -> None:
        """Compilation is deterministic, so an unchanged plan must not invent a
        version — a new version number should mean something changed."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)

        first = await service.compile_prompts(campaign.id)
        second = await service.compile_prompts(campaign.id)

        assert first.canonical_prompt is not None and second.canonical_prompt is not None
        assert first.canonical_prompt.version == second.canonical_prompt.version
        assert first.canonical_prompt.id == second.canonical_prompt.id

    async def test_the_prompt_records_where_it_came_from(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        view = await _service(session, workspace, storage).compile_prompts(campaign.id)

        prompt = view.prompts[0]
        assert prompt.specification_version == 2
        assert prompt.canonical_prompt_id == view.canonical_prompt.id
        assert "v2" in prompt.trace()

    async def test_every_configured_provider_gets_its_own_prompt(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        view = await _service(
            session, workspace, storage, image_providers="mock,gemini"
        ).compile_prompts(campaign.id)

        assert {p.provider for p in view.prompts} == {"mock", "gemini"}
        # Same idea, different wording: that is what an adapter is for.
        assert len({p.text for p in view.prompts}) == 2


# ---------------------------------------------------------------- generation
class TestGenerationJobs:
    async def test_a_batch_starts_pending_and_completes(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)

        view, _ = await service.start(campaign.id)
        assert view.batch is not None
        assert [job.status for job in view.batch.jobs] == [JobStatus.PENDING]

        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        assert after.batch is not None
        assert [job.status for job in after.batch.jobs] == [JobStatus.COMPLETED]
        assert after.batch.is_complete() is True
        assert after.batch.outcome() == "All 1 provider succeeded."

    async def test_a_completed_job_produces_a_stored_plate(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        (asset,) = after.batch.assets
        assert asset.kind is AssetKind.VISUAL_PLATE
        assert asset.width > 0 and asset.height > 0
        assert asset.mime_type == "image/png"
        assert asset.specification_version == 2
        # The bytes are really there.
        assert await storage.get(asset.storage_key)

    async def test_a_jpeg_plate_is_persisted_as_jpeg(
        self, session, workspace, storage, monkeypatch
    ) -> None:
        """The Gemini path end to end, without Gemini. The mime type the
        provider reports must reach the storage key, the stored object and the
        asset row — nothing along the way may assume PNG."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)

        def _jpeg_provider(settings, name=None):
            return _JpegImageProvider()

        monkeypatch.setattr("app.services.generation.build_image_provider", _jpeg_provider)

        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        (asset,) = after.batch.assets
        assert asset.mime_type == "image/jpeg"
        assert asset.storage_key.endswith(".jpg")
        assert asset.kind is AssetKind.VISUAL_PLATE
        assert (asset.width, asset.height) == (320, 320)

        # The bytes really are a JPEG, and really are readable back out.
        stored = await storage.get(asset.storage_key)
        assert stored.startswith(b"\xff\xd8\xff")
        with Image.open(io.BytesIO(stored)) as image:
            assert image.format == "JPEG"

    async def test_a_failing_provider_fails_its_job_with_a_readable_reason(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, mock_failure_mode="rate_limit")

        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        (job,) = after.batch.jobs
        assert job.status is JobStatus.FAILED
        assert job.error is not None
        assert job.error.code == "PROVIDER_RATE_LIMITED"
        assert "rate limit" in job.error.message.lower()
        assert after.batch.assets == []

    async def test_a_generation_never_leaves_a_job_running(
        self, session, workspace, storage
    ) -> None:
        """The UI must never show a card that spins forever."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, mock_failure_mode="blocked")
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        assert all(job.is_terminal() for job in after.batch.jobs)

    async def test_generation_cannot_start_without_an_approved_specification(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(
            session, workspace.org, approved=False
        )
        with pytest.raises(Conflict):
            await _service(session, workspace, storage).start(campaign.id)

    async def test_the_view_explains_why_generation_is_blocked(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(
            session, workspace.org, approved=False
        )
        view = await _service(session, workspace, storage).current(campaign.id)
        assert view.can_generate is False
        assert view.blocked_reason and "approve" in view.blocked_reason.lower()

    async def test_starting_twice_does_not_charge_twice(self, session, workspace, storage) -> None:
        """The idempotency key is the replay guard: a repeated request must not
        create a second job for the same prompt and attempt."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)

        await service.start(campaign.id)
        await service.start(campaign.id)

        jobs = await GenerationJobRepository(session, workspace.org.id).for_campaign(campaign.id)
        assert len(jobs) == 1


class TestPartialSuccess:
    async def test_two_of_three_succeeding_is_reported_as_partial(
        self, session, workspace, storage
    ) -> None:
        """A batch that produced usable plates is not a failure, and says so."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, image_providers="mock,gemini")

        view, _ = await service.start(campaign.id)
        assert len(view.batch.jobs) == 2

        # Gemini has no credentials here, so it fails while mock succeeds —
        # a real partial outcome rather than a simulated one.
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        assert len(after.batch.succeeded) == 1
        assert len(after.batch.failed) == 1
        assert after.batch.outcome() == "1/2 providers succeeded — 1 failed."
        # The plate the working provider produced survived the other's failure.
        assert len(after.batch.assets) == 1
        assert after.batch.assets[0].provider == "mock"

    async def test_one_provider_failing_does_not_cancel_another(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, image_providers="mock,gemini")
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        statuses = {job.provider: job.status for job in after.batch.jobs}
        assert statuses["mock"] is JobStatus.COMPLETED
        assert statuses["gemini"] is JobStatus.FAILED


class TestRetry:
    async def test_a_failed_job_can_be_retried_and_succeed(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        failing = _service(session, workspace, storage, mock_failure_mode="timeout")
        view, _ = await failing.start(campaign.id)
        await failing.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        failed = (await failing.current(campaign.id)).batch.jobs[0]
        assert failed.status is JobStatus.FAILED
        assert failed.can_retry() is True

        working = _service(session, workspace, storage)
        retried_id = await working.retry(campaign.id, uuid.UUID(failed.id))
        await working.run_jobs([retried_id])

        after = await working.current(campaign.id)
        assert len(after.batch.succeeded) == 1
        assert len(after.batch.assets) == 1

    async def test_a_retry_is_a_new_attempt(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        failing = _service(session, workspace, storage, mock_failure_mode="timeout")
        view, _ = await failing.start(campaign.id)
        await failing.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])
        failed = (await failing.current(campaign.id)).batch.jobs[0]

        retried_id = await failing.retry(campaign.id, uuid.UUID(failed.id))
        row = await GenerationJobRepository(session, workspace.org.id).get(retried_id)
        assert row.attempt == 2
        # A new attempt is a new key, so a deliberate retry is allowed to charge.
        assert row.idempotency_key != failed.idempotency_key

    async def test_a_completed_job_cannot_be_retried(self, session, workspace, storage) -> None:
        """Re-running a success would pay twice for an image already in hand."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        completed = (await service.current(campaign.id)).batch.jobs[0]
        with pytest.raises(Conflict):
            await service.retry(campaign.id, uuid.UUID(completed.id))

    async def test_an_unknown_job_cannot_be_retried(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).retry(campaign.id, uuid.uuid4())


class TestStorageKeys:
    def test_a_key_is_generated_not_derived_from_input(self) -> None:
        org, campaign, job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        key = generated_asset_key(
            organization_id=org, campaign_id=campaign, job_id=job, mime_type="image/png"
        )
        assert key.startswith(f"org-{org}/campaign-{campaign}/generated/")
        assert key.endswith(".png")
        assert ".." not in key and "/../" not in key

    def test_two_keys_for_the_same_job_never_collide(self) -> None:
        args = {
            "organization_id": uuid.uuid4(),
            "campaign_id": uuid.uuid4(),
            "job_id": uuid.uuid4(),
            "mime_type": "image/png",
        }
        assert generated_asset_key(**args) != generated_asset_key(**args)

    def test_a_jpeg_plate_gets_a_jpg_extension(self) -> None:
        """Gemini returns JPEG and nothing else. A key ending `.png` over
        JPEG bytes misleads every tool that trusts an extension."""
        key = generated_asset_key(
            organization_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            mime_type="image/jpeg",
        )
        assert key.endswith(".jpg")

    def test_an_unknown_mime_type_does_not_produce_a_strange_extension(self) -> None:
        key = generated_asset_key(
            organization_id=uuid.uuid4(),
            campaign_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            mime_type="application/x-evil; name=../../etc/passwd",
        )
        assert key.endswith(".bin")

    async def test_a_stored_plate_lives_under_its_own_organization(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        (asset,) = (await service.current(campaign.id)).batch.assets
        assert asset.storage_key.startswith(f"org-{workspace.org.id}/")
        assert str(campaign.id) in asset.storage_key


class TestTenancy:
    async def test_another_organizations_campaign_cannot_be_generated_for(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign = await _campaign_with_approved_specification(session, theirs)

        with pytest.raises(NotFound):
            await _service(session, workspace, storage).start(their_campaign.id)

    async def test_another_organizations_generation_is_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign = await _campaign_with_approved_specification(session, theirs)

        with pytest.raises(NotFound):
            await _service(session, workspace, storage).current(their_campaign.id)

    async def test_another_organizations_jobs_are_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign = await _campaign_with_approved_specification(session, theirs)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        await _service(session, their_workspace, storage).start(their_campaign.id)

        mine = GenerationJobRepository(session, workspace.org.id)
        assert await mine.for_campaign(their_campaign.id) == []

    async def test_another_organizations_assets_are_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign = await _campaign_with_approved_specification(session, theirs)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage)
        view, _ = await their_service.start(their_campaign.id)
        await their_service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        their_assets = (await their_service.current(their_campaign.id)).batch.assets
        assert their_assets, "the other organization really did generate something"

        mine = GeneratedAssetRepository(session, workspace.org.id)
        assert await mine.get(uuid.UUID(their_assets[0].id)) is None
        assert await mine.for_campaign(their_campaign.id) == []

    async def test_an_arbitrary_job_id_cannot_be_retried_across_the_boundary(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign = await _campaign_with_approved_specification(session, theirs)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage, mock_failure_mode="timeout")
        view, _ = await their_service.start(their_campaign.id)
        await their_service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])
        their_job = (await their_service.current(their_campaign.id)).batch.jobs[0]

        mine = await _campaign_with_approved_specification(session, workspace.org)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).retry(mine.id, uuid.UUID(their_job.id))


class TestDatabaseConstraints:
    """The migration's CHECK constraints are real, not decorative.

    Alembic does not autogenerate CHECK constraints, so it is worth proving
    that the ones declared on these new tables actually reached the database.
    """

    async def test_an_unknown_job_status_is_rejected(self, session, workspace) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        from sqlalchemy import text

        # A savepoint: the statement must fail without taking the fixture's
        # outer transaction down with it.
        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "insert into generation_jobs (organization_id, campaign_id, "
                    "model_prompt_id, specification_id, specification_version, batch_id, "
                    "provider, model, status, idempotency_key, attempt) values "
                    "(:org, :camp, :prompt, :spec, 1, :batch, 'mock', 'm', 'ELSEWHERE', 'k', 1)"
                ),
                {
                    "org": workspace.org.id,
                    "camp": campaign.id,
                    "prompt": uuid.uuid4(),
                    "spec": uuid.uuid4(),
                    "batch": uuid.uuid4(),
                },
            )
        assert "status_valid" in str(caught.value)
        await savepoint.rollback()

    async def test_an_unknown_asset_kind_is_rejected(self, session, workspace) -> None:
        """`VISUAL_PLATE` says what a raw model output is; a row claiming to be
        something else would erase that distinction."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        from sqlalchemy import text

        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "insert into generated_assets (organization_id, campaign_id, "
                    "generation_job_id, model_prompt_id, specification_id, "
                    "specification_version, provider, model, kind, storage_key, "
                    "mime_type, width, height, meta) values "
                    "(:org, :camp, :job, :prompt, :spec, 1, 'mock', 'm', 'FINISHED_POSTER', "
                    "'k', 'image/png', 1, 1, '{}')"
                ),
                {
                    "org": workspace.org.id,
                    "camp": campaign.id,
                    "job": uuid.uuid4(),
                    "prompt": uuid.uuid4(),
                    "spec": uuid.uuid4(),
                },
            )
        assert "kind_valid" in str(caught.value)
        await savepoint.rollback()

    async def test_an_idempotency_key_cannot_repeat(self, session, workspace, storage) -> None:
        """The unique constraint is the last line of the replay guard, below
        the service's own check."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        job = view.batch.jobs[0]

        repository = GenerationJobRepository(session, workspace.org.id)
        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await repository.create(
                campaign_id=campaign.id,
                model_prompt_id=uuid.uuid4(),
                specification_id=uuid.uuid4(),
                specification_version=1,
                batch_id=uuid.uuid4(),
                provider="mock",
                model="m",
                idempotency_key=job.idempotency_key,
            )
        assert "idempotency_key" in str(caught.value)
        await savepoint.rollback()


class TestOutcomeWording:
    """`outcome()` speaks about providers, so it must count providers.

    A retry adds a job. Counting jobs made a two-provider batch report
    "1/3 providers succeeded" after one retry, which is not a thing that
    happened.
    """

    async def test_a_retry_does_not_invent_a_third_provider(
        self, session, workspace, storage
    ) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, image_providers="mock,gemini")
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        failed = (await service.current(campaign.id)).batch.failed[0]
        retried = await service.retry(campaign.id, uuid.UUID(failed.id))
        await service.run_jobs([retried])

        after = await service.current(campaign.id)
        assert len(after.batch.jobs) == 3, "the earlier attempt is kept as history"
        assert after.batch.outcome() == "1/2 providers succeeded — 1 failed."

    async def test_the_latest_attempt_is_what_counts(self, session, workspace, storage) -> None:
        """A provider that failed and then succeeded on retry is a success."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        failing = _service(session, workspace, storage, mock_failure_mode="timeout")
        view, _ = await failing.start(campaign.id)
        await failing.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        working = _service(session, workspace, storage)
        failed = (await working.current(campaign.id)).batch.failed[0]
        retried = await working.retry(campaign.id, uuid.UUID(failed.id))
        await working.run_jobs([retried])

        after = await working.current(campaign.id)
        assert after.batch.outcome() == "All 1 provider succeeded."
        assert [job.attempt for job in after.batch.latest_per_provider()] == [2]

    async def test_one_provider_is_singular(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        assert "1 provider finished" in view.batch.outcome() or "provider" in view.batch.outcome()
        assert "providers" not in view.batch.outcome()


class TestProviderAvailability:
    async def test_a_provider_with_no_adapter_says_so(self, session, workspace, storage) -> None:
        """Leonardo has a prompt adapter but no image adapter in this build.
        The job must explain that, not report a generic crash."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, image_providers="leonardo")
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        (job,) = (await service.current(campaign.id)).batch.jobs
        assert job.status is JobStatus.FAILED
        assert job.error is not None
        assert "not available" in job.error.message
        assert job.error.code == "PROVIDER_UNAVAILABLE"

    async def test_several_plates_per_provider_can_be_requested(
        self, session, workspace, storage
    ) -> None:
        """Comparing variants from one provider is a real use, so the count is
        configuration rather than a constant."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage, generation_images_per_job=3)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        after = await service.current(campaign.id)
        assert len(after.batch.assets) == 3
        # Distinct plates, not the same image three times.
        assert len({asset.storage_key for asset in after.batch.assets}) == 3


class TestBatchOrdering:
    async def test_two_batches_in_one_transaction_are_distinguishable(
        self, session, workspace, storage
    ) -> None:
        """Postgres' `now()` is transaction-start time, so jobs created in one
        transaction share `created_at` exactly. Without a Python-side stamp,
        "which batch is latest?" is answered arbitrarily — and a regeneration
        after a revision silently returns the *previous* batch's jobs.
        """
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)

        first_view, first_batch = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(j.id) for j in first_view.batch.jobs])

        # A second batch in the same transaction, exactly as a revision does.
        repository = GenerationJobRepository(session, workspace.org.id)
        prompt_id = (await repository.for_campaign(campaign.id))[0].model_prompt_id
        second_batch = uuid.uuid4()
        await repository.create(
            campaign_id=campaign.id,
            model_prompt_id=prompt_id,
            specification_id=uuid.uuid4(),
            specification_version=2,
            batch_id=second_batch,
            provider="mock",
            model="mock-image-1",
            idempotency_key=f"second-{uuid.uuid4()}",
        )

        assert await repository.latest_batch_id(campaign.id) == second_batch
        assert second_batch != first_batch


class TestIdempotency:
    """What `API_SPEC.md` §Conventions now documents, and used to get wrong.

    The document claimed every work-starting endpoint accepted an
    `Idempotency-Key` header and that replaying it returned the original result.
    No route ever read that header (audit findings DOC-2 / BG-5). What is real is
    better than what was documented: the key is *derived server-side* from
    `(prompt, provider, model, attempt)` and enforced by a unique constraint, so
    a replay cannot double-charge even from a client that sends nothing — and a
    deliberate retry still can, because the attempt number is part of the key.

    Untested until this fix pass, which is how the documentation drifted away
    from it without anything failing.
    """

    async def test_replaying_start_creates_no_second_job(self, session, workspace, storage) -> None:
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)

        first, _ = await service.start(campaign.id)
        second, _ = await service.start(campaign.id)

        assert first.batch is not None and second.batch is not None
        assert [job.id for job in second.batch.jobs] == [job.id for job in first.batch.jobs]

    async def test_replaying_start_charges_the_provider_once(
        self, session, workspace, storage
    ) -> None:
        """The failure the mechanism exists to prevent: one click, one charge."""
        campaign = await _campaign_with_approved_specification(session, workspace.org)
        service = _service(session, workspace, storage)
        view, _ = await service.start(campaign.id)
        await service.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        await service.start(campaign.id)

        after = await service.current(campaign.id)
        assert after.batch is not None
        assert len(after.batch.assets) == 1, "a replay generated a second image"

    async def test_the_key_is_derived_rather_than_supplied(
        self, session, workspace, storage
    ) -> None:
        """Derived from the work, so two callers asking for the same thing
        collide whether or not either sent a header."""
        from app.services.generation import _idempotency_key

        prompt_id = uuid.uuid4()
        assert _idempotency_key(prompt_id, "mock", "m", attempt=1) == _idempotency_key(
            prompt_id, "mock", "m", attempt=1
        )

    async def test_a_deliberate_retry_gets_its_own_key(self) -> None:
        """The distinction the attempt number carries: a replay must not charge
        twice, and a retry must be allowed to."""
        from app.services.generation import _idempotency_key

        prompt_id = uuid.uuid4()
        assert _idempotency_key(prompt_id, "mock", "m", attempt=1) != _idempotency_key(
            prompt_id, "mock", "m", attempt=2
        )
