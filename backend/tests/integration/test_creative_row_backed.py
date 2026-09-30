"""A creative stage that exists in the tables but not in a checkpoint.

Audit findings HL-1 and HL-2. The hyperlocal benchmark writes an approved
Creative Direction set and an approved Creative Specification through the
repositories and deliberately stops before generation
(`scripts/seed_benchmark.py`, `docs/HYPERLOCAL_BENCHMARK.md`). No graph ever
runs for those nine campaigns, so `graph.aget_state()` is empty for them.

Two things went wrong because of that, and both are asserted here:

* **HL-1** — `GET /creative` reported no directions and no specification, which
  is the opposite of what the database holds. The screen the benchmark's own
  demo storyline opens at step 3 showed "No creative routes yet".
* **HL-2** — that empty state offers "Develop creative routes", and pressing it
  ran the Creative Director from scratch, arrived back at version 1, and wrote
  its output over the approved seeded row.

The checkpoint-backed path is the subject of `test_creative_graph.py` and must
keep behaving exactly as it did; the last test here pins the boundary.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.common import Role
from app.domain.creative import CreativeDirection, CreativeDirectionSet, CreativeSpecification
from app.domain.workspace import Principal, User
from app.errors import Conflict
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.creative import (
    CreativeDirectionSetRepository,
    CreativeSpecificationRepository,
)
from app.services.creative_stage import CreativeStageService
from tests.integration.conftest import TEST_DATABASE_URL
from tests.integration.test_creative_graph import _brand, _confirmed_campaign

pytestmark = pytest.mark.integration


def _settings():
    """Settings whose checkpointer points at the *test* database.

    `get_settings()` reads `backend/.env`, so a service built from it would look
    for a checkpoint in the developer's own database. These tests assert on the
    absence of one, which would then be an accident rather than a fact.
    """
    from app.config import Settings, get_settings

    base = get_settings().model_dump()
    base.update(
        {
            "database_url": TEST_DATABASE_URL,
            "database_url_sync": TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql"),
            "llm_provider": "mock",
            "image_provider": "mock",
            "image_providers": "",
            "embedding_provider": "mock",
            "mock_failure_mode": "none",
        }
    )
    return Settings(**base)


def _service(session, workspace, storage) -> CreativeStageService:
    return CreativeStageService(
        session,
        Principal(
            user=User(id=str(workspace.user.id), email=workspace.user.email),
            organization_id=str(workspace.org.id),
            role=Role.ADMIN,
        ),
        settings=_settings(),
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
        storage=storage,
    )


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "store"))


def _direction_payload(campaign_id: uuid.UUID, direction_id: uuid.UUID, title: str) -> dict:
    """The shape `seed_benchmark.py` writes: a `CreativeDirectionSet` dump.

    Built through the domain models rather than hand-written, for the same
    reason the benchmark dataset is: a literal dict drifts from the contract it
    claims to exercise without anything failing. Fictional values throughout.
    """
    return CreativeDirectionSet(
        campaign_id=str(campaign_id),
        version=1,
        directions=[
            CreativeDirection(
                id=str(direction_id),
                campaign_id=str(campaign_id),
                ordinal=1,
                title=title,
                big_idea="The house is judged by how it feels when it rains.",
                strategic_rationale="Monsoon light is the usable local fact, not motif.",
                emotional_angle="relief",
                headline=title,
                cta="Book a home visit",
                visual_metaphor="water held outside, calm held inside",
                composition="off-centre, window left",
                subject="a cane chair by an open window",
                environment="a contemporary Kochi apartment",
                lighting="flat overcast, no hard shadow",
                brand_integration="lime plaster wall carries the palette",
                product_integration="the chair is the product, in use",
            )
        ],
        recommended_ordinal=1,
        recommendation_reasons=["Selected for the benchmark."],
    ).model_dump(mode="json")


def _specification_payload(campaign_id: uuid.UUID, direction_id: uuid.UUID) -> dict:
    return CreativeSpecification(
        campaign_id=str(campaign_id),
        direction_id=str(direction_id),
        version=1,
        concept="A room that stays calm through the monsoon.",
        emotional_angle="relief",
        headline="മഴ പെയ്യുമ്പോൾ.",
        cta="Book a home visit",
        visual_metaphor="water held outside, calm held inside",
        composition="off-centre, window left",
        subject="a cane chair by an open window",
        environment="a contemporary Kochi apartment",
        lighting="flat overcast, no hard shadow",
        brand_integration="lime plaster wall carries the palette",
        product_integration="the chair is the product, in use",
        visual_story="Flat monsoon light across a cane chair and lime plaster.",
        camera="35mm, eye level",
        mood=["calm", "humid", "unhurried"],
        locked_fields=["cta"],
    ).model_dump(mode="json")


async def _seeded_rows(session, org_id, campaign_id: uuid.UUID) -> uuid.UUID:
    """Exactly what the benchmark seed does: both gates already decided."""
    direction_id = uuid.uuid4()
    await CreativeDirectionSetRepository(session, org_id).upsert_version(
        campaign_id=campaign_id,
        version=1,
        payload=_direction_payload(campaign_id, direction_id, "When It Rains."),
        selected_direction_id=direction_id,
    )
    specifications = CreativeSpecificationRepository(session, org_id)
    row = await specifications.upsert_version(
        campaign_id=campaign_id,
        version=1,
        direction_id=direction_id,
        payload=_specification_payload(campaign_id, direction_id),
    )
    await specifications.approve(row, user_id=None)
    return direction_id


class TestARowSeededCampaignReportsItsOwnCreative:
    """HL-1. The rows are the product state; the checkpoint is execution state."""

    async def test_current_reports_the_seeded_direction_set(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        direction_id = await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()

        turn = await _service(session, workspace, storage).current(campaign.id)

        assert turn.direction_set is not None, "the seeded routes must be visible"
        assert len(turn.direction_set.directions) == 1
        assert turn.direction_set.directions[0].title == "When It Rains."
        assert turn.selected_direction_id == str(direction_id)

    async def test_current_reports_the_approved_specification(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()

        turn = await _service(session, workspace, storage).current(campaign.id)

        assert turn.specification is not None
        assert turn.specification.headline == "മഴ പെയ്യുമ്പോൾ."
        assert turn.approved is True, "the seed approved Gate 2; the view must say so"

    async def test_no_gate_is_reported_without_an_execution_to_resume(
        self, session, workspace, storage
    ) -> None:
        """A gate is open when the graph is parked on its node. Nothing is
        parked here, so an Approve button would have no checkpoint to resume."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()

        turn = await _service(session, workspace, storage).current(campaign.id)

        assert turn.gate is None
        assert turn.gaps == [], "CreativeContext has no table; a gap list would be invented"

    async def test_a_campaign_with_neither_rows_nor_checkpoint_is_still_empty(
        self, session, workspace, storage
    ) -> None:
        """The fix must not make an untouched campaign look started."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()

        turn = await _service(session, workspace, storage).current(campaign.id)

        assert turn.direction_set is None
        assert turn.specification is None
        assert turn.approved is False


class TestStartingTheStageCannotDestroySeededCreative:
    """HL-2. The one-click overwrite, from both ends."""

    async def test_start_does_not_replace_an_approved_seeded_direction_set(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()
        repo = CreativeDirectionSetRepository(session, workspace.org.id)
        before = dict((await repo.latest(campaign.id)).payload)

        await _service(session, workspace, storage).start(campaign.id)

        after = (await repo.latest(campaign.id)).payload
        assert after == before, "pressing Develop creative routes must change nothing"

    async def test_start_reports_the_existing_creative_instead_of_rebuilding_it(
        self, session, workspace, storage
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()

        turn = await _service(session, workspace, storage).start(campaign.id)

        assert turn.direction_set is not None
        assert turn.direction_set.directions[0].title == "When It Rains."
        assert turn.approved is True

    async def test_start_creates_no_second_version(self, session, workspace, storage) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()

        await _service(session, workspace, storage).start(campaign.id)

        versions = await CreativeDirectionSetRepository(session, workspace.org.id).list_versions(
            campaign.id
        )
        assert [row.version for row in versions] == [1]

    async def test_the_repository_refuses_to_overwrite_an_approved_set(
        self, session, workspace
    ) -> None:
        """The second layer. Even a caller that reaches past the service is refused."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        direction_id = await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()
        repo = CreativeDirectionSetRepository(session, workspace.org.id)

        with pytest.raises(Conflict):
            await repo.upsert_version(
                campaign_id=campaign.id,
                version=1,
                payload=_direction_payload(campaign.id, direction_id, "Something Else."),
            )

    async def test_re_projecting_the_same_approved_set_is_still_a_no_op(
        self, session, workspace
    ) -> None:
        """Idempotent, not immutable: the graph re-projects the same state
        several times as the stage advances, and that must keep working."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        direction_id = await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()
        repo = CreativeDirectionSetRepository(session, workspace.org.id)
        same = _direction_payload(campaign.id, direction_id, "When It Rains.")

        row = await repo.upsert_version(campaign_id=campaign.id, version=1, payload=same)

        assert row.payload == same

    async def test_an_unapproved_set_may_still_be_replaced(self, session, workspace) -> None:
        """The guard is about approval, not about age. A set nobody decided on
        is still the graph's to rewrite."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        direction_id = uuid.uuid4()
        repo = CreativeDirectionSetRepository(session, workspace.org.id)
        await repo.upsert_version(
            campaign_id=campaign.id,
            version=1,
            payload=_direction_payload(campaign.id, direction_id, "First Attempt."),
        )
        await session.commit()

        row = await repo.upsert_version(
            campaign_id=campaign.id,
            version=1,
            payload=_direction_payload(campaign.id, direction_id, "Second Attempt."),
        )

        assert row.payload["directions"][0]["title"] == "Second Attempt."


class TestApprovedSpecificationsAreProtectedTheSameWay:
    async def test_the_repository_refuses_to_overwrite_an_approved_specification(
        self, session, workspace
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        direction_id = await _seeded_rows(session, workspace.org.id, campaign.id)
        await session.commit()
        changed = _specification_payload(campaign.id, direction_id) | {"headline": "Different."}

        with pytest.raises(Conflict):
            await CreativeSpecificationRepository(session, workspace.org.id).upsert_version(
                campaign_id=campaign.id,
                version=1,
                direction_id=direction_id,
                payload=changed,
            )


class TestTheCheckpointStillWins:
    async def test_a_campaign_with_a_checkpoint_is_read_from_the_checkpoint(
        self, session, workspace, storage
    ) -> None:
        """The boundary between the two paths.

        Starting a campaign with no rows runs the graph as it always has, and
        the resulting view carries what only graph state can carry — the open
        gate and the context's gaps. If this ever came back `None`, the row
        fallback would have swallowed the real path.
        """
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()

        turn = await _service(session, workspace, storage).start(campaign.id)

        assert turn.gate == "strategy_gate", "the real graph must still park on Gate 1"
        assert turn.direction_set is not None
        assert len(turn.direction_set.directions) == 3
