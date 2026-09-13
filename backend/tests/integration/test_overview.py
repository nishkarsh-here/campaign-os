"""The campaign command centre.

The thing worth testing about a dashboard is not that it renders — it is that
it *agrees with the screens it summarises*. A read model that derives its own
answer becomes a second source of truth, and the first time the two disagree
the dashboard is the one people believe.

So these tests assert the overview against the same services the individual
pages read, and that a stage nobody has reached says so rather than reading as
finished.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.common import Channel
from app.errors import NotFound
from app.services.composition_stage import CompositionService
from app.services.overview import (
    ATTENTION,
    BLOCKED,
    DONE,
    PENDING,
    STAGES,
    CampaignOverviewService,
)
from tests.integration.factories import make_org
from tests.integration.test_final_composition import (
    _principal,
    _principal_for_org,
    _seed,
    _settings,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def storage():
    """The same storage root the composition tests use — fixtures are not
    inherited by importing helpers from another module."""
    from app.providers.local.storage import LocalStorageProvider
    from tests.integration.test_final_composition import _STORAGE_ROOT

    return LocalStorageProvider(_STORAGE_ROOT)


def _overview_service(session, principal, storage):
    from app.providers.mock.embedding import MockEmbeddingProvider
    from app.providers.mock.llm import MockLLMProvider

    return CampaignOverviewService(
        session,
        principal,
        settings=_settings(),
        storage=storage,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
    )


def _by_key(view, key: str):
    stage = next((s for s in view.stages if s.key == key), None)
    assert stage is not None, f"no {key} stage in the overview"
    return stage


class TestTheOverviewReadsRealState:
    async def test_every_declared_stage_is_present_and_explained(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        view = await _overview_service(session, _principal(workspace), storage).overview(
            campaign.id
        )

        assert [s.key for s in view.stages] == [key for key, _ in STAGES]
        assert all(s.detail for s in view.stages), "a stage with no sentence explains nothing"
        assert view.brand_name, "the overview names the brand"

    async def test_an_unstarted_stage_never_reads_as_finished(
        self, session, workspace, storage
    ) -> None:
        """The failure that matters: a campaign that has generated nothing must
        not show a green composition stage."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        view = await _overview_service(session, _principal(workspace), storage).overview(
            campaign.id
        )

        assert _by_key(view, "composition").state in (PENDING, BLOCKED, ATTENTION)
        assert view.final_assets == []
        assert view.next_stage is not None, "something is outstanding and it should say what"

    async def test_composing_moves_the_stage_and_the_counts(
        self, session, workspace, storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, storage)
        principal = _principal(workspace)
        composition = CompositionService(session, principal, settings=_settings(), storage=storage)
        await composition.compose(campaign.id, channel=Channel.INSTAGRAM_POST)
        await composition.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)
        await composition.add_variant(campaign.id, channel=Channel.LINKEDIN)
        await composition.render_final(campaign.id, channel=Channel.LINKEDIN)

        view = await _overview_service(session, principal, storage).overview(campaign.id)

        stage = _by_key(view, "composition")
        assert stage.state is DONE or stage.state == DONE
        assert len(view.final_assets) == 2
        assert set(view.composed_channels) == {
            Channel.INSTAGRAM_POST.value,
            Channel.LINKEDIN.value,
        }
        assert Channel.INSTAGRAM_POST.value not in view.available_channels

    async def test_the_composition_stage_agrees_with_the_composition_service(
        self, session, workspace, storage
    ) -> None:
        """The anti-drift test. Both sides are asked the same question."""
        campaign, _, _ = await _seed(session, workspace.org, storage)
        principal = _principal(workspace)
        composition = CompositionService(session, principal, settings=_settings(), storage=storage)
        await composition.compose(campaign.id, channel=Channel.INSTAGRAM_POST)
        await composition.render_final(campaign.id, channel=Channel.INSTAGRAM_POST)

        direct = await composition.current(campaign.id, channel=Channel.INSTAGRAM_POST)
        view = await _overview_service(session, principal, storage).overview(campaign.id)

        assert [a.id for a in view.final_assets] == [a.id for a in direct.final_assets]
        assert view.composed_channels == direct.composed_channels
        assert view.latest_layout_version == (direct.layout.version if direct.layout else None)


class TestTenancy:
    async def test_another_organizations_campaign_is_not_found(
        self, session, workspace, storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, storage)

        service = _overview_service(session, _principal(workspace), storage)

        with pytest.raises(NotFound):
            await service.overview(their_campaign.id)

    async def test_the_owner_still_sees_it(self, session, workspace, storage) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, storage)

        service = _overview_service(session, _principal_for_org(workspace.user, theirs), storage)

        assert (await service.overview(their_campaign.id)).campaign_id == str(their_campaign.id)

    async def test_an_unknown_campaign_is_not_found(self, session, workspace, storage) -> None:
        service = _overview_service(session, _principal(workspace), storage)
        with pytest.raises(NotFound):
            await service.overview(uuid.uuid4())


class TestOverHttp:
    async def test_the_endpoint_returns_the_full_shape(
        self, client, session, workspace, api_storage
    ) -> None:
        campaign, _, _ = await _seed(session, workspace.org, api_storage)
        await session.commit()

        response = await client.get(f"/v1/campaigns/{campaign.id}/overview")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["title"] == campaign.title
        assert [s["key"] for s in body["stages"]] == [key for key, _ in STAGES]
        assert body["brand_name"]

    async def test_another_organizations_campaign_is_404(
        self, client, session, workspace, api_storage
    ) -> None:
        theirs = await make_org(session)
        their_campaign, _, _ = await _seed(session, theirs, api_storage)
        await session.commit()

        response = await client.get(f"/v1/campaigns/{their_campaign.id}/overview")

        assert response.status_code == 404
