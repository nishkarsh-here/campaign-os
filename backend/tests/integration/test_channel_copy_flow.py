"""Per-channel copy across the seams that need a database (Milestone 11).

Three properties that cannot be asserted on a pure function:

* an override is not approved copy until **Gate 2** says so — which means the
  composition layer must not see it before then
* an override may only name a channel the **Campaign Specification** declares,
  a question the Creative Specification cannot answer for itself
* the composition editor still refuses to rewrite a call to action, now
  checking against the channel's *own* approved words

The pure resolver, the revision loop and the byte-identical promise are in
`tests/test_channel_copy.py`.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.common import Channel, utc_now
from app.domain.creative import ChannelCopy, CreativeSpecification, copy_for
from app.errors import Conflict, NotFound, ValidationFailed
from app.services.composition_stage import CompositionService
from tests.integration.factories import make_org
from tests.integration.test_final_composition import (
    _principal,
    _principal_for_org,
    _seed,
    _settings,
)

pytestmark = pytest.mark.integration

STORY = Channel.INSTAGRAM_STORY
POST = Channel.INSTAGRAM_POST
LINKEDIN = Channel.LINKEDIN


@pytest.fixture
def storage():
    from app.providers.local.storage import LocalStorageProvider
    from tests.integration.test_final_composition import _STORAGE_ROOT

    return LocalStorageProvider(_STORAGE_ROOT)


def _composition(session, workspace, storage) -> CompositionService:
    return CompositionService(session, _principal(workspace), settings=_settings(), storage=storage)


async def _creative_service(session, workspace, storage):
    from app.providers.mock.embedding import MockEmbeddingProvider
    from app.providers.mock.llm import MockLLMProvider
    from app.services.creative_stage import CreativeStageService

    return CreativeStageService(
        session,
        _principal(workspace),
        settings=_settings(),
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
        storage=storage,
    )


async def _campaign_channels(session, org, campaign_id, channels: list[Channel]) -> None:
    """Declare the campaign's channels, which is what an override is checked against."""
    from app.db.models import CampaignSpecificationRow

    session.add(
        CampaignSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign_id,
            version=1,
            schema_version=1,
            payload={
                "campaign_id": str(campaign_id),
                "title": "Launch",
                "objective": "Get FS-9 specified at design stage",
                "audience": "Architects in Mumbai",
                "product": "FS-9 facade system",
                "key_message": "Built to outlast the building it clads",
                "cta": "Request the specification pack",
                "channels": [c.value for c in channels],
            },
        )
    )
    await session.flush()


async def _approved_version(session, org, campaign, specification, **fields):
    """A newer, *approved* specification version. What Gate 2 leaves behind."""
    return await _version(session, org, campaign, specification, approved=True, **fields)


async def _unapproved_draft(session, org, campaign, specification, **fields):
    """A newer, *unapproved* specification version — a draft nobody signed off."""
    return await _version(session, org, campaign, specification, approved=False, **fields)


async def _version(session, org, campaign, specification, *, approved: bool, **fields):
    from app.db.models import CreativeSpecificationRow

    draft = CreativeSpecification.model_validate(
        specification.model_dump(mode="json") | {"version": 2} | fields
    )
    session.add(
        CreativeSpecificationRow(
            organization_id=org.id,
            campaign_id=campaign.id,
            direction_id=uuid.UUID(draft.direction_id),
            version=2,
            payload=draft.model_dump(mode="json"),
            approved_at=utc_now() if approved else None,
        )
    )
    await session.flush()
    return draft


# ===========================================================================
class TestGateTwoGovernsOverrides:
    """Acceptance criterion 3. An override is approved copy or it is nothing.

    Composition reads the *latest* specification and refuses unless it is
    approved (M9 behaviour, unchanged here). So an unapproved draft carrying an
    override does not reach a deliverable by any path: the composition stage
    stops before it reads a word of it.
    """

    async def test_composition_refuses_while_a_draft_override_is_unapproved(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        await _unapproved_draft(
            session,
            workspace.org,
            campaign,
            specification,
            channel_copy={STORY.value: {"headline": "Not approved yet"}},
        )

        with pytest.raises(Conflict, match="Approve a Creative Specification"):
            await service.add_variant(campaign.id, channel=STORY, source=POST)

    async def test_an_approved_override_does_reach_composition(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        revised = await _approved_version(
            session,
            workspace.org,
            campaign,
            specification,
            channel_copy={STORY.value: {"headline": "Outlasts the building"}},
        )

        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        await service.add_variant(campaign.id, channel=STORY, source=POST)

        story = await service.current(campaign.id, channel=STORY)
        post = await service.current(campaign.id, channel=POST)
        assert story.layout is not None and post.layout is not None
        assert story.layout.by_role("headline").content == "Outlasts the building"
        assert post.layout.by_role("headline").content == revised.headline, "only the story moved"


class TestOnlyDeclaredChannels:
    """Acceptance criterion 6.

    The Campaign Specification owns the channel list. The Creative
    Specification cannot answer "does this campaign run stories?" for itself,
    so the check lives at the service boundary where both are in scope.
    """

    async def _editable(self, session, workspace, storage, channels: list[Channel]):
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        await _campaign_channels(session, workspace.org, campaign.id, channels)
        await _unapproved_draft(session, workspace.org, campaign, specification)
        return campaign, await _creative_service(session, workspace, storage)

    async def test_an_undeclared_channel_is_refused(self, session, workspace, storage) -> None:
        campaign, service = await self._editable(session, workspace, storage, [POST, LINKEDIN])

        with pytest.raises(ValidationFailed, match="does not run"):
            await service.edit_specification(
                campaign.id, {"channel_copy": {STORY.value: {"headline": "Outlasts it"}}}
            )

    async def test_the_refusal_names_the_channels_that_are_allowed(
        self, session, workspace, storage
    ) -> None:
        """A refusal a user cannot act on is barely better than silence."""
        campaign, service = await self._editable(session, workspace, storage, [POST, LINKEDIN])

        with pytest.raises(ValidationFailed) as raised:
            await service.edit_specification(
                campaign.id, {"channel_copy": {STORY.value: {"headline": "Outlasts it"}}}
            )
        assert set(raised.value.details["channels"]) == {POST.value, LINKEDIN.value}

    async def test_a_declared_channel_is_accepted(self, session, workspace, storage) -> None:
        campaign, service = await self._editable(session, workspace, storage, [POST, STORY])

        updated = await service.edit_specification(
            campaign.id, {"channel_copy": {STORY.value: {"headline": "Outlasts it"}}}
        )

        assert copy_for(updated, STORY).headline == "Outlasts it"
        assert copy_for(updated, POST).headline == updated.headline
        assert "channel_copy" in updated.human_edited_fields, "a human wrote this"

    async def test_a_campaign_with_no_specification_is_refused(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        await _unapproved_draft(session, workspace.org, campaign, specification)
        service = await _creative_service(session, workspace, storage)

        with pytest.raises(Conflict, match="Campaign Specification"):
            await service.edit_specification(
                campaign.id, {"channel_copy": {POST.value: {"headline": "x"}}}
            )


class TestTheEditorChecksTheResolvedCta:
    """Acceptance criterion 4.

    The guard compared against `specification.cta` before M11. A channel with
    its own approved call to action would then have had the very words the plan
    says it should carry rejected as a brand violation.
    """

    async def _with_override(self, session, workspace, storage):
        from app.db.models import CreativeSpecificationRow

        campaign, specification, _ = await _seed(session, workspace.org, storage)
        revised = CreativeSpecification.model_validate(
            specification.model_dump(mode="json")
            | {"version": 2, "channel_copy": {LINKEDIN.value: {"cta": "Talk to our facade team"}}}
        )
        session.add(
            CreativeSpecificationRow(
                organization_id=workspace.org.id,
                campaign_id=campaign.id,
                direction_id=uuid.UUID(revised.direction_id),
                version=2,
                payload=revised.model_dump(mode="json"),
                approved_at=utc_now(),
            )
        )
        await session.flush()
        return campaign, revised

    async def test_the_channels_own_cta_is_accepted(self, session, workspace, storage) -> None:
        campaign, revised = await self._with_override(session, workspace, storage)
        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        await service.add_variant(campaign.id, channel=LINKEDIN, source=POST)

        view = await service.current(campaign.id, channel=LINKEDIN)
        cta = view.layout.by_role("cta")
        assert cta is not None
        assert cta.content == "Talk to our facade team", "the variant carries its own words"

        # Re-submitting exactly what is approved for this channel is a no-op,
        # not a violation.
        await service.edit(
            campaign.id,
            channel=LINKEDIN,
            edits={"elements": {cta.id: {"content": "Talk to our facade team"}}},
        )

    async def test_the_default_cta_is_refused_on_an_overridden_channel(
        self, session, workspace, storage
    ) -> None:
        """The sharp edge. On this channel the *default* is now the wrong copy."""
        campaign, revised = await self._with_override(session, workspace, storage)
        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        await service.add_variant(campaign.id, channel=LINKEDIN, source=POST)

        view = await service.current(campaign.id, channel=LINKEDIN)
        cta = view.layout.by_role("cta")

        with pytest.raises(ValidationFailed, match="approved campaign fact") as raised:
            await service.edit(
                campaign.id,
                channel=LINKEDIN,
                edits={"elements": {cta.id: {"content": revised.cta}}},
            )
        assert raised.value.details["approved"] == "Talk to our facade team"

    async def test_an_unrelated_channel_still_guards_the_default(
        self, session, workspace, storage
    ) -> None:
        campaign, revised = await self._with_override(session, workspace, storage)
        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)

        view = await service.current(campaign.id, channel=POST)
        cta = view.layout.by_role("cta")
        assert cta.content == revised.cta

        with pytest.raises(ValidationFailed, match="approved campaign fact"):
            await service.edit(
                campaign.id,
                channel=POST,
                edits={"elements": {cta.id: {"content": "Talk to our facade team"}}},
            )


class TestRenderingAcrossChannels:
    async def test_each_channel_renders_its_own_words(self, session, workspace, storage) -> None:
        from app.db.models import CreativeSpecificationRow

        campaign, specification, _ = await _seed(session, workspace.org, storage)
        revised = CreativeSpecification.model_validate(
            specification.model_dump(mode="json")
            | {
                "version": 2,
                "channel_copy": {
                    STORY.value: {"headline": "Outlasts the building"},
                    LINKEDIN.value: {"headline": "Specified to last"},
                },
            }
        )
        session.add(
            CreativeSpecificationRow(
                organization_id=workspace.org.id,
                campaign_id=campaign.id,
                direction_id=uuid.UUID(revised.direction_id),
                version=2,
                payload=revised.model_dump(mode="json"),
                approved_at=utc_now(),
            )
        )
        await session.flush()

        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        rendered = {}
        for channel in (STORY, LINKEDIN):
            await service.add_variant(campaign.id, channel=channel, source=POST)
            rendered[channel] = await service.render_final(campaign.id, channel=channel)
        rendered[POST] = await service.render_final(campaign.id, channel=POST)

        headlines = {}
        for channel in (POST, STORY, LINKEDIN):
            view = await service.current(campaign.id, channel=channel)
            headlines[channel] = view.layout.by_role("headline").content

        assert headlines[STORY] == "Outlasts the building"
        assert headlines[LINKEDIN] == "Specified to last"
        assert headlines[POST] == copy_for(revised, POST).headline
        assert len({a.storage_key for a in rendered.values()}) == 3, "three distinct files"

    async def test_an_override_does_not_disturb_a_channel_without_one(
        self, session, workspace, storage
    ) -> None:
        campaign, specification, _ = await _seed(session, workspace.org, storage)
        service = _composition(session, workspace, storage)
        await service.compose(campaign.id, channel=POST)
        before = await service.render_final(campaign.id, channel=POST)
        before_bytes = await storage.get(before.storage_key)

        assert copy_for(specification, POST).headline == specification.headline
        assert ChannelCopy().is_empty()
        assert before_bytes, "the baseline render exists"


class TestChannelCopyTenancy:
    """One organization cannot read or mutate another's per-channel copy.

    `channel_copy` has no data path of its own — it rides inside the
    `CreativeSpecification` payload, and every route to it goes through an
    already-scoped repository. So this guarantee is *inherited* from the
    parametrized probe over all 26 scoped repositories rather than newly built.

    It is still asserted here, on the two concrete paths a caller actually has,
    because "the words a competitor wrote for their LinkedIn banner" is exactly
    the kind of thing that must not leak, and a guarantee nobody names is one
    nobody notices breaking.
    """

    SECRET = "Their unreleased positioning line"

    async def _theirs(self, session, workspace, storage):
        """Another organization's campaign, carrying an approved override."""
        theirs = await make_org(session)
        campaign, specification, _ = await _seed(session, theirs, storage)
        await _approved_version(
            session,
            theirs,
            campaign,
            specification,
            channel_copy={LINKEDIN.value: {"headline": self.SECRET}},
        )
        return theirs, campaign

    async def test_another_organization_cannot_read_it(self, session, workspace, storage) -> None:
        _, campaign = await self._theirs(session, workspace, storage)
        mine = await _creative_service(session, workspace, storage)

        with pytest.raises(NotFound):
            await mine.current(campaign.id)

    async def test_the_words_never_reach_the_other_organization(
        self, session, workspace, storage
    ) -> None:
        """The strongest form: not just a refusal, but the text never appearing.

        A `NotFound` on one method proves that method. This checks the override
        text is absent from everything the other organization *can* see.
        """
        _, theirs = await self._theirs(session, workspace, storage)
        mine, _, _ = await _seed(session, workspace.org, storage)

        service = await _creative_service(session, workspace, storage)
        composition = _composition(session, workspace, storage)
        await composition.compose(mine.id, channel=POST)
        await composition.add_variant(mine.id, channel=LINKEDIN, source=POST)

        visible = repr(await service.current(mine.id)) + repr(
            await composition.current(mine.id, channel=LINKEDIN)
        )

        assert self.SECRET not in visible
        assert theirs.id != mine.id

    async def test_another_organization_cannot_mutate_it(self, session, workspace, storage) -> None:
        _, campaign = await self._theirs(session, workspace, storage)
        mine = await _creative_service(session, workspace, storage)

        with pytest.raises(NotFound):
            await mine.edit_specification(
                campaign.id, {"channel_copy": {LINKEDIN.value: {"headline": "Ours now"}}}
            )

    async def test_the_owner_still_sees_their_own(self, session, workspace, storage) -> None:
        """The other half. A refusal that refuses everyone proves nothing."""
        theirs, campaign = await self._theirs(session, workspace, storage)
        composition = CompositionService(
            session,
            _principal_for_org(workspace.user, theirs),
            settings=_settings(),
            storage=storage,
        )
        await composition.compose(campaign.id, channel=POST)
        await composition.add_variant(campaign.id, channel=LINKEDIN, source=POST)

        view = await composition.current(campaign.id, channel=LINKEDIN)
        assert view.layout.by_role("headline").content == self.SECRET
