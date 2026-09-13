"""The revision loop end to end, and the boundaries around it.

The centrepiece is `TestTheFullRevisionLoop`: v1 → feedback → delta → v2 →
regenerate → re-evaluate, asserting at every step that v1 is untouched, that
only the requested fields moved, that the new asset points at v2, and that the
v1 asset still points at v1. If that test passes, Milestone 8 does what it says.

Nothing here reaches a live provider.
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
from app.domain.creative import CreativeSpecification, NegativeConstraints
from app.domain.guardian import GUARDIAN_VERSION, GuardianVerdict
from app.domain.revision import FieldChange, RevisionDelta, RevisionStatus
from app.domain.workspace import Principal, User
from app.errors import Conflict, NotFound, ValidationFailed
from app.providers.base import ImageRequest
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.image import MockImageProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.creative import CreativeSpecificationRepository
from app.repositories.evaluation import CreativeEvaluationRepository
from app.repositories.generation import GeneratedAssetRepository
from app.repositories.revision import (
    BrandGuardianRepository,
    SpecificationRevisionRepository,
)
from app.services.evaluation_stage import EvaluationService
from app.services.generation import GenerationService
from app.services.revision_stage import RevisionStageService
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

#: Names the environment directly, so the planner has something unambiguous to
#: act on — the central Milestone 8 example.
FEEDBACK = "Everything is good except the environment — make it feel more local."


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


def _specification(campaign_id: uuid.UUID, version: int = 1) -> CreativeSpecification:
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
        environment="a modern construction site",
        lighting="hard directional studio light",
        palette=["#1F2933", "#E4572E"],
        product_integration="the system is the subject, not a prop",
        brand_integration="colour and restraint, not a badge",
        negative_constraints=NegativeConstraints(forbidden_elements=["stock handshakes"]),
    )


async def _campaign(session, org, storage, *, with_asset: bool = True):
    """A campaign with an approved v1 and, optionally, a plate generated from it."""
    brand = BrandProfileRow(
        organization_id=org.id,
        name=f"Northline {uuid.uuid4().hex[:6]}",
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": "Northline",
            "prohibited_claims": ["indestructible"],
            "colors": [{"name": "Graphite", "hex": "#1F2933", "role": "primary"}],
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

    specification = _specification(campaign_id)
    session.add(
        CreativeSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            direction_id=uuid.UUID(specification.direction_id),
            version=1,
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
    await session.flush()

    asset = None
    if with_asset:
        asset = await _asset_for(session, org, campaign, specification, version=1)
    return campaign, specification, asset


async def _asset_for(
    session, org, campaign, specification: CreativeSpecification, *, version: int
) -> GeneratedAssetRow:
    """A real stored plate, linked to the specification version it came from."""
    canonical = CanonicalPromptRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        specification_id=uuid.UUID(specification.id),
        specification_version=version,
        version=version,
        payload={"subject": specification.subject},
        source_fingerprint=uuid.uuid4().hex,
    )
    session.add(canonical)
    await session.flush()
    prompt = ModelPromptRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        canonical_prompt_id=canonical.id,
        provider="mock",
        model="mock-image-1",
        version=version,
        payload={"text": specification.subject},
    )
    session.add(prompt)
    await session.flush()
    job = GenerationJobRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        model_prompt_id=prompt.id,
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

    (image,) = await MockImageProvider().generate(
        ImageRequest(prompt=f"plate v{version} for {campaign.id}", aspect_ratio="1:1")
    )
    key = f"org-{org.id}/campaign-{campaign.id}/generated/{uuid.uuid4().hex}.png"
    await _storage_for(session).put(key, image.data, mime_type="image/png")
    row = GeneratedAssetRow(
        organization_id=org.id,
        campaign_id=campaign.id,
        generation_job_id=job.id,
        model_prompt_id=prompt.id,
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
    await session.flush()
    return row


_STORAGE: dict[int, LocalStorageProvider] = {}


def _storage_for(session) -> LocalStorageProvider:
    """One storage root per test, keyed by the session it belongs to."""
    return _STORAGE[id(session)]


@pytest.fixture
def storage(tmp_path, session) -> LocalStorageProvider:
    provider = LocalStorageProvider(str(tmp_path))
    _STORAGE[id(session)] = provider
    yield provider
    _STORAGE.pop(id(session), None)


def _service(session, workspace, storage, **overrides) -> RevisionStageService:
    return RevisionStageService(
        session,
        _principal(workspace),
        settings=_settings(**overrides),
        storage=storage,
        llm=MockLLMProvider(overrides.get("mock_failure_mode", "none")),
        embeddings=MockEmbeddingProvider(),
    )


def _generation(session, workspace, storage) -> GenerationService:
    return GenerationService(
        session,
        _principal(workspace),
        settings=_settings(),
        storage=storage,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
    )


def _evaluation(session, workspace, storage) -> EvaluationService:
    return EvaluationService(
        session,
        _principal(workspace),
        settings=_settings(),
        storage=storage,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
    )


# ===========================================================================
class TestTheFullRevisionLoop:
    """The most important test in Milestone 8.

    v1 → human feedback → delta → v2 → regenerate → evaluate, proving at each
    step that history survived and that only what was asked for changed.
    """

    async def test_v1_feedback_v2_regenerate_reevaluate(self, session, workspace, storage) -> None:
        campaign, v1, v1_asset = await _campaign(session, workspace.org, storage)
        assert v1_asset is not None
        v1_snapshot = v1.model_dump(mode="json")

        service = _service(session, workspace, storage)

        # --- the human asks for one thing -------------------------------
        revision = await service.propose_revision(
            campaign.id, feedback=FEEDBACK, source_asset_id=v1_asset.id
        )
        assert revision.status == RevisionStatus.PROPOSED.value
        assert revision.from_version == 1
        assert revision.to_version is None, "nothing is applied before approval"

        delta = RevisionDelta.model_validate(revision.delta)
        assert "environment" in delta.touched_fields()
        assert delta.user_feedback == FEEDBACK

        # --- gate 1: approve the delta ----------------------------------
        applied = await service.approve_delta(campaign.id)
        assert applied.status == RevisionStatus.APPLIED.value
        assert applied.to_version == 2
        assert applied.changed_fields == ["environment"]

        specifications = CreativeSpecificationRepository(session, workspace.org.id)
        v1_row = await specifications.by_version(campaign.id, 1)
        v2_row = await specifications.by_version(campaign.id, 2)
        assert v1_row is not None and v2_row is not None
        v2 = CreativeSpecification.model_validate(v2_row.payload)

        # v1 is untouched, byte for byte.
        assert v1_row.payload == v1_snapshot

        # Only the requested field moved.
        assert v2.environment != v1.environment
        for name in ("concept", "headline", "cta", "subject", "composition", "lighting"):
            assert getattr(v2, name) == getattr(v1, name), f"{name} changed uninvited"

        # Approved facts survived.
        assert v2.cta == "Request the specification pack"
        assert v2.product_integration == v1.product_integration
        assert v2.brand_integration == v1.brand_integration
        assert v2.negative_constraints.no_text_in_image is True

        # --- gate 2: approve the revised specification ------------------
        approved = await service.approve_revised_specification(campaign.id)
        assert approved.status == RevisionStatus.APPROVED.value
        refreshed = await specifications.by_version(campaign.id, 2)
        assert refreshed is not None and refreshed.approved_at is not None

        # --- regenerate through the existing M6 machinery ---------------
        generation = _generation(session, workspace, storage)
        view, _ = await generation.start(campaign.id)
        assert view.batch is not None
        await generation.run_jobs([uuid.UUID(job.id) for job in view.batch.jobs])

        assets = await GeneratedAssetRepository(session, workspace.org.id).for_campaign(campaign.id)
        new_assets = [a for a in assets if a.id != v1_asset.id]
        assert new_assets, "regeneration produced a plate"

        # The new asset points at v2; the old one still points at v1.
        assert all(a.specification_version == 2 for a in new_assets)
        await session.refresh(v1_asset)
        assert v1_asset.specification_version == 1

        # --- re-evaluate against v2 -------------------------------------
        evaluation = _evaluation(session, workspace, storage)
        _, claimed = await evaluation.start(campaign.id, asset_ids=[new_assets[0].id])
        await evaluation.run_evaluations(claimed)

        rows = await CreativeEvaluationRepository(session, workspace.org.id).for_campaign(
            campaign.id
        )
        fresh = [r for r in rows if r.generated_asset_id == new_assets[0].id]
        assert fresh, "the new asset was evaluated"
        assert fresh[0].specification_version == 2, "evaluated against v2, not v1"
        assert fresh[0].payload is not None
        assert fresh[0].payload["specification_version"] == 2

        # --- history is intact ------------------------------------------
        history = await SpecificationRevisionRepository(session, workspace.org.id).history(
            campaign.id
        )
        assert len(history) == 1
        assert history[0].user_feedback == FEEDBACK
        assert history[0].from_version == 1 and history[0].to_version == 2
        assert history[0].source_asset_id == v1_asset.id
        assert history[0].requested_by == workspace.user.id


class TestGuardian:
    async def test_an_asset_can_be_brand_checked(self, session, workspace, storage) -> None:
        campaign, _, asset = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)

        view, claimed = await service.start_guardian(campaign.id)
        assert view.in_flight == 1
        await service.run_guardian_checks(claimed)

        rows = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        assert len(rows) == 1
        assert rows[0].status == JobStatus.COMPLETED.value
        assert rows[0].verdict in {v.value for v in GuardianVerdict}
        assert rows[0].payload is not None
        assert rows[0].specification_version == 1
        assert rows[0].guardian_version == GUARDIAN_VERSION
        assert asset is not None and rows[0].generated_asset_id == asset.id

    async def test_the_verdict_follows_from_the_checks(self, session, workspace, storage) -> None:
        from app.domain.guardian import BrandGuardianResult, decide_verdict

        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start_guardian(campaign.id)
        await service.run_guardian_checks(claimed)

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        result = BrandGuardianResult.model_validate(row.payload)
        expected, _, _ = decide_verdict(result.checks)
        assert result.verdict is expected

    async def test_deterministic_checks_are_marked_as_such(
        self, session, workspace, storage
    ) -> None:
        """ "We matched a prohibited claim" and "a model thought so" carry
        different weight, and the UI shows which is which."""
        from app.domain.guardian import BrandGuardianResult

        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start_guardian(campaign.id)
        await service.run_guardian_checks(claimed)

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        result = BrandGuardianResult.model_validate(row.payload)
        assert any(check.deterministic for check in result.checks)
        assert any(not check.deterministic for check in result.checks)

    async def test_a_prohibited_claim_in_the_plan_is_blocking(
        self, session, workspace, storage
    ) -> None:
        """Decided in code from the Brand Brain, not asked of a model."""
        from app.domain.creative_context import BrandGuardrails
        from app.domain.guardian import CheckStatus, GuardianCheck, Severity
        from app.services.brand_guardian import GuardianContext, deterministic_checks
        from app.services.evaluation_stage import _to_asset

        campaign, specification, asset = await _campaign(session, workspace.org, storage)
        assert asset is not None
        offending = specification.model_copy(update={"concept": "An indestructible facade system"})
        checks = deterministic_checks(
            GuardianContext(
                asset=_to_asset(asset),
                specification=offending,
                guardrails=BrandGuardrails(prohibited_claims=["indestructible"]),
            )
        )
        claim = next(c for c in checks if c.check is GuardianCheck.CLAIM_SAFETY)
        assert claim.status is CheckStatus.FAIL
        assert claim.severity is Severity.BLOCKING
        assert claim.deterministic is True

    async def test_a_provider_failure_is_recorded_not_a_pass(
        self, session, workspace, storage
    ) -> None:
        """An outage must never read as brand approval."""
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage, mock_failure_mode="rate_limit")
        _, claimed = await service.start_guardian(campaign.id)
        await service.run_guardian_checks(claimed)

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        assert row.status == JobStatus.FAILED.value
        assert row.verdict is None
        assert row.error is not None

    async def test_a_failed_check_can_be_retried(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        failing = _service(session, workspace, storage, mock_failure_mode="timeout")
        _, claimed = await failing.start_guardian(campaign.id)
        await failing.run_guardian_checks(claimed)

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        working = _service(session, workspace, storage)
        retried = await working.retry_guardian(campaign.id, row.id)
        await working.run_guardian_checks([retried])

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        assert row.status == JobStatus.COMPLETED.value

    async def test_a_completed_check_cannot_be_retried(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        _, claimed = await service.start_guardian(campaign.id)
        await service.run_guardian_checks(claimed)
        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        with pytest.raises(Conflict):
            await service.retry_guardian(campaign.id, row.id)

    async def test_checking_without_assets_is_a_conflict(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage, with_asset=False)
        service = _service(session, workspace, storage)
        state = await service.guardian_state(campaign.id)
        assert state.can_check is False
        with pytest.raises(Conflict):
            await service.start_guardian(campaign.id)

    async def test_an_asset_is_checked_against_its_own_plan(
        self, session, workspace, storage
    ) -> None:
        """After a revision, "latest" is a plan the v1 asset never saw."""
        campaign, v1, v1_asset = await _campaign(session, workspace.org, storage)
        assert v1_asset is not None
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        await service.approve_delta(campaign.id)

        _, claimed = await service.start_guardian(campaign.id, asset_ids=[v1_asset.id])
        await service.run_guardian_checks(claimed)

        (row,) = await BrandGuardianRepository(session, workspace.org.id).for_campaign(campaign.id)
        assert row.specification_version == 1


class TestRevisionGates:
    async def test_feedback_produces_a_proposal_and_changes_nothing_yet(
        self, session, workspace, storage
    ) -> None:
        campaign, v1, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)

        specifications = CreativeSpecificationRepository(session, workspace.org.id)
        assert await specifications.by_version(campaign.id, 2) is None
        row = await specifications.by_version(campaign.id, 1)
        assert row is not None
        assert CreativeSpecification.model_validate(row.payload).environment == v1.environment

    async def test_a_human_can_edit_the_delta_before_approving(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)

        edited = RevisionDelta(
            iteration=1,
            user_feedback=FEEDBACK,
            interpretation="Change the lighting instead.",
            keep=["environment", "concept"],
            change=[
                FieldChange(
                    field="lighting", reason="the human decided", new_value="soft dusk light"
                )
            ],
        )
        await service.edit_delta(campaign.id, delta=edited)
        applied = await service.approve_delta(campaign.id)

        assert applied.changed_fields == ["lighting"]
        row = await CreativeSpecificationRepository(session, workspace.org.id).by_version(
            campaign.id, 2
        )
        assert row is not None
        v2 = CreativeSpecification.model_validate(row.payload)
        assert v2.lighting == "soft dusk light"

    async def test_an_edited_delta_still_obeys_the_locks(self, session, workspace, storage) -> None:
        """An edit must not become the way around the rules."""
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)

        with pytest.raises(ValueError, match="locked"):
            RevisionDelta(
                iteration=1,
                user_feedback=FEEDBACK,
                keep=[],
                change=[FieldChange(field="cta", reason="sneaky", new_value="Buy now")],
            )

    async def test_a_revision_can_be_discarded(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        rejected = await service.reject_revision(campaign.id)

        assert rejected.status == RevisionStatus.REJECTED.value
        assert (
            await CreativeSpecificationRepository(session, workspace.org.id).by_version(
                campaign.id, 2
            )
            is None
        )
        # And the record of the question survives.
        history = await SpecificationRevisionRepository(session, workspace.org.id).history(
            campaign.id
        )
        assert len(history) == 1

    async def test_only_one_revision_may_be_open(self, session, workspace, storage) -> None:
        """Two open proposals would race to become the next version."""
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        with pytest.raises(Conflict, match="already open"):
            await service.propose_revision(campaign.id, feedback="and the lighting too")

    async def test_a_second_revision_follows_the_first(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        await service.approve_delta(campaign.id)
        await service.approve_revised_specification(campaign.id)

        second = await service.propose_revision(
            campaign.id, feedback="Now make the lighting softer."
        )
        assert second.iteration == 2
        assert second.from_version == 2, "revises the version now approved"

    async def test_gate_two_cannot_be_skipped(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        with pytest.raises(Conflict, match="not APPLIED"):
            await service.approve_revised_specification(campaign.id)

    async def test_gate_one_cannot_be_repeated(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        await service.approve_delta(campaign.id)
        with pytest.raises(Conflict, match="not PROPOSED"):
            await service.approve_delta(campaign.id)

    async def test_vague_feedback_is_a_question_not_a_revision(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        with pytest.raises(ValidationFailed):
            await service.propose_revision(campaign.id, feedback="hmm not sure about it")

    async def test_revising_without_an_approved_plan_is_a_conflict(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        row = await CreativeSpecificationRepository(session, workspace.org.id).by_version(
            campaign.id, 1
        )
        assert row is not None
        row.approved_at = None
        await session.flush()

        service = _service(session, workspace, storage)
        with pytest.raises(Conflict):
            await service.propose_revision(campaign.id, feedback=FEEDBACK)

    async def test_the_state_view_exposes_the_before_and_after(
        self, session, workspace, storage
    ) -> None:
        campaign, v1, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)
        await service.propose_revision(campaign.id, feedback=FEEDBACK)
        await service.approve_delta(campaign.id)

        state = await service.revision_state(campaign.id)
        assert state.current is not None
        assert state.source_specification is not None
        assert state.revised_specification is not None
        assert state.source_specification.environment == v1.environment
        assert state.revised_specification.environment != v1.environment


class TestTenancy:
    async def _theirs(self, session, storage):
        theirs = await make_org(session)
        campaign, specification, asset = await _campaign(session, theirs, storage)
        return theirs, campaign, specification, asset

    async def test_another_organizations_campaign_cannot_be_guardian_checked(
        self, session, workspace, storage
    ) -> None:
        _, campaign, _, _ = await self._theirs(session, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).start_guardian(campaign.id)

    async def test_another_organizations_guardian_state_is_invisible(
        self, session, workspace, storage
    ) -> None:
        _, campaign, _, _ = await self._theirs(session, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).guardian_state(campaign.id)

    async def test_another_organizations_guardian_results_are_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs, campaign, _, _ = await self._theirs(session, storage)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage)
        _, claimed = await their_service.start_guardian(campaign.id)
        await their_service.run_guardian_checks(claimed)

        mine = BrandGuardianRepository(session, workspace.org.id)
        assert await mine.for_campaign(campaign.id) == []
        assert await mine.get(claimed[0]) is None

    async def test_another_organizations_campaign_cannot_be_revised(
        self, session, workspace, storage
    ) -> None:
        _, campaign, _, _ = await self._theirs(session, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).propose_revision(
                campaign.id, feedback=FEEDBACK
            )

    async def test_another_organizations_revisions_are_invisible(
        self, session, workspace, storage
    ) -> None:
        theirs, campaign, _, _ = await self._theirs(session, storage)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        await _service(session, their_workspace, storage).propose_revision(
            campaign.id, feedback=FEEDBACK
        )

        mine = SpecificationRevisionRepository(session, workspace.org.id)
        assert await mine.history(campaign.id) == []
        assert await mine.open_revision(campaign.id) is None

    async def test_another_organizations_asset_cannot_seed_a_revision(
        self, session, workspace, storage
    ) -> None:
        """Their asset cannot be smuggled in as the source of my revision —
        which is how their brand context would have leaked into my plan."""
        _, _, _, their_asset = await self._theirs(session, storage)
        mine, _, _ = await _campaign(session, workspace.org, storage)
        assert their_asset is not None

        with pytest.raises(NotFound):
            await _service(session, workspace, storage).propose_revision(
                mine.id, feedback=FEEDBACK, source_asset_id=their_asset.id
            )

    async def test_a_revision_uses_only_its_own_brand(self, session, workspace, storage) -> None:
        """Two campaigns, two brands: each revision is planned against its own."""
        first, _, _ = await _campaign(session, workspace.org, storage)
        second, _, _ = await _campaign(session, workspace.org, storage)
        service = _service(session, workspace, storage)

        await service.propose_revision(first.id, feedback=FEEDBACK)
        await service.propose_revision(second.id, feedback=FEEDBACK)

        repository = SpecificationRevisionRepository(session, workspace.org.id)
        for campaign in (first, second):
            rows = await repository.history(campaign.id)
            assert len(rows) == 1
            assert rows[0].campaign_id == campaign.id

    async def test_another_organizations_guardian_result_cannot_be_retried(
        self, session, workspace, storage
    ) -> None:
        theirs, campaign, _, _ = await self._theirs(session, storage)
        their_workspace = type("W", (), {"org": theirs, "user": workspace.user})()
        their_service = _service(session, their_workspace, storage, mock_failure_mode="timeout")
        _, claimed = await their_service.start_guardian(campaign.id)
        await their_service.run_guardian_checks(claimed)

        mine, _, _ = await _campaign(session, workspace.org, storage)
        with pytest.raises(NotFound):
            await _service(session, workspace, storage).retry_guardian(mine.id, claimed[0])


class TestDatabaseConstraints:
    async def test_an_unknown_verdict_is_rejected(self, session, workspace, storage) -> None:
        campaign, _, asset = await _campaign(session, workspace.org, storage)
        from sqlalchemy import text

        assert asset is not None
        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await session.execute(
                text(
                    "insert into brand_guardian_results (organization_id, campaign_id, "
                    "generated_asset_id, specification_id, specification_version, "
                    "guardian_version, status, verdict) values "
                    "(:org, :camp, :asset, :spec, 1, 'v1', 'COMPLETED', 'PROBABLY')"
                ),
                {
                    "org": workspace.org.id,
                    "camp": campaign.id,
                    "asset": asset.id,
                    "spec": uuid.uuid4(),
                },
            )
        assert "verdict_valid" in str(caught.value)
        await savepoint.rollback()

    async def test_one_revision_per_campaign_iteration(self, session, workspace, storage) -> None:
        campaign, _, _ = await _campaign(session, workspace.org, storage)
        repository = SpecificationRevisionRepository(session, workspace.org.id)
        await repository.propose(
            campaign_id=campaign.id,
            iteration=1,
            user_feedback="x",
            delta={"iteration": 1, "user_feedback": "x"},
            from_version=1,
        )
        savepoint = await session.begin_nested()
        with pytest.raises(Exception) as caught:
            await repository.propose(
                campaign_id=campaign.id,
                iteration=1,
                user_feedback="y",
                delta={"iteration": 1, "user_feedback": "y"},
                from_version=1,
            )
        assert "iteration" in str(caught.value)
        await savepoint.rollback()
