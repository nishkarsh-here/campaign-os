"""The Milestone 5 creative graph.

The mandatory walk: start → context → directions → gate 1 → resume in a fresh
process → approve → specification → gate 2 → resume → preserve human edits →
complete.

Every resume rebuilds the saver and the graph, so nothing carries over in
memory — only the Postgres checkpoint.
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.config import get_settings
from app.db.models import BrandProfileRow, CampaignRow
from app.domain.creative import PROTECTED_CAMPAIGN_FACTS
from app.graph.build import build_creative_graph, creative_thread_id
from app.graph.nodes.deps import NodeDeps
from app.graph.serde import checkpointer_kwargs
from app.graph.state import CampaignState
from app.providers.local.storage import LocalStorageProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from app.repositories.campaigns import CampaignSpecificationRepository
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration


@pytest.fixture
def dsn() -> str:
    return get_settings().database_url_sync.replace("/campaign_os", "/campaign_os_test")


@pytest.fixture
def storage(tmp_path) -> LocalStorageProvider:
    return LocalStorageProvider(str(tmp_path / "store"))


def _deps(session, org_id, storage) -> NodeDeps:
    return NodeDeps(
        session=session,
        organization_id=org_id,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
        storage=storage,
    )


async def _brand(session, org, name: str = "Northline") -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": name,
            "prohibited_claims": ["indestructible"],
            "voice": {
                "tone_attributes": ["confident", "technical"],
                "person": None,
                "writing_rules": [],
                "avoid": [],
            },
        },
    )
    session.add(row)
    await session.flush()
    return row


async def _confirmed_campaign(session, org, brand) -> CampaignRow:
    """A campaign whose discovery is finished — the creative stage's entry."""
    cid = uuid.uuid4()
    campaign = CampaignRow(
        id=cid,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title="Maharashtra launch",
        status="SPECIFICATION_CONFIRMED",
        thread_id=str(cid),
        draft_inputs={},
        creative_preferences={},
    )
    session.add(campaign)
    await session.flush()

    await CampaignSpecificationRepository(session, org.id).create_version(
        campaign_id=cid,
        payload={
            "campaign_id": str(cid),
            "title": "Maharashtra launch",
            "objective": "Establish the premium specification choice",
            "audience": "Architects in Maharashtra",
            "product": "FS-9 facade system",
            "key_message": "Engineered to outlast the building it clads",
            "cta": "Request a specification pack",
            "channels": ["linkedin"],
            "region": "Maharashtra, India",
        },
    )
    return campaign


class TestCreativeWalk:
    """Steps 1–11 of the mandatory graph test, in order."""

    async def test_the_full_creative_walk(self, session, workspace, storage, dsn) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}
        deps = _deps(session, workspace.org.id, storage)

        # 1–4. Start, load context, generate directions, interrupt at gate 1.
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(deps, checkpointer=saver)
            result = await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            assert result.get("__interrupt__"), "must pause for strategy approval"
            snapshot = await graph.aget_state(config)
            assert snapshot.next == ("human_strategy_approval",)
            state = CampaignState.model_validate(snapshot.values)

        assert state.creative_context is not None
        assert state.creative_context.specification is not None
        assert state.direction_set is not None
        assert len(state.direction_set.directions) == 3
        chosen = state.direction_set.directions[1]

        # 5–7. Fresh saver and graph; approve; specification is built.
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(deps, checkpointer=saver)
            before = await graph.aget_state(config)
            assert before.next == ("human_strategy_approval",)

            await graph.ainvoke(
                Command(resume={"decision": "APPROVE", "target_id": chosen.id}), config
            )
            snapshot = await graph.aget_state(config)
            state = CampaignState.model_validate(snapshot.values)

        assert state.selected_direction is not None
        assert state.selected_direction.id == chosen.id
        assert state.creative_specification is not None

        # 8. Interrupted at gate 2.
        assert snapshot.next == ("human_specification_approval",)

        # 9–11. Resume again, approve, and the stage completes.
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(deps, checkpointer=saver)
            await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config)
            final = await graph.aget_state(config)
            state = CampaignState.model_validate(final.values)

        assert not final.next, "the creative stage is complete"
        from app.domain.approval import Decision, Gate

        assert state.approval_states[Gate.SPECIFICATION.value].decision is Decision.APPROVE
        # Milestone 5 stops here: no image, no prompts.
        assert state.model_prompts == []
        assert state.generated_assets == []

    async def test_human_edits_survive_a_regeneration(
        self, session, workspace, storage, dsn
    ) -> None:
        """Step 10: a regeneration must never undo an edit."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}
        deps = _deps(session, workspace.org.id, storage)

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(deps, checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            state = CampaignState.model_validate((await graph.aget_state(config)).values)
            chosen = state.direction_set.directions[0]
            await graph.ainvoke(
                Command(resume={"decision": "APPROVE", "target_id": chosen.id}), config
            )
            state = CampaignState.model_validate((await graph.aget_state(config)).values)

            # A human edits the plan, and it is pushed into graph state.
            edited = state.creative_specification.model_copy(
                update={
                    "headline": "A human wrote this headline",
                    "human_edited_fields": ["headline"],
                }
            )
            await graph.aupdate_state(config, {"creative_specification": edited})

            # Ask for changes: the builder runs again.
            await graph.ainvoke(
                Command(resume={"decision": "REQUEST_REVISION", "feedback": "warmer"}),
                config,
            )
            after = CampaignState.model_validate((await graph.aget_state(config)).values)

        assert after.creative_specification is not None
        assert after.creative_specification.headline == "A human wrote this headline"
        assert "headline" in after.creative_specification.human_edited_fields

    async def test_rejection_regenerates_and_preserves_campaign_facts(
        self, session, workspace, storage, dsn
    ) -> None:
        """ "Too technical, make it aspirational" must not change the product."""
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}
        deps = _deps(session, workspace.org.id, storage)

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(deps, checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            first = CampaignState.model_validate((await graph.aget_state(config)).values)
            first_version = first.direction_set.version

            await graph.ainvoke(
                Command(
                    resume={
                        "decision": "REQUEST_REVISION",
                        "feedback": "Direction 2 is too technical. Make it more aspirational.",
                    }
                ),
                config,
            )
            after = CampaignState.model_validate((await graph.aget_state(config)).values)

        # A new version, not a mutation of the old one.
        assert after.direction_set.version == first_version + 1
        assert after.direction_set.revision_of_version == first_version

        # The delta protects every campaign fact.
        assert after.creative_revision is not None
        assert set(PROTECTED_CAMPAIGN_FACTS) <= set(after.creative_revision.keep)
        assert "emotional_angle" in after.creative_revision.change

        # And the context the director reads is unchanged.
        assert after.creative_context.specification.product == "FS-9 facade system"
        assert after.creative_context.specification.audience == "Architects in Maharashtra"

    async def test_directions_are_meaningfully_different(
        self, session, workspace, storage, dsn
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(
                _deps(session, workspace.org.id, storage), checkpointer=saver
            )
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            state = CampaignState.model_validate((await graph.aget_state(config)).values)

        directions = state.direction_set.directions
        assert state.direction_set.diversity is not None
        assert state.direction_set.diversity.passed, state.direction_set.diversity.describe()
        assert len({d.emotional_angle for d in directions}) == 3
        assert len({d.subject for d in directions}) == 3

    async def test_directions_respect_the_brand_and_specification(
        self, session, workspace, storage, dsn
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _confirmed_campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_creative_graph(
                _deps(session, workspace.org.id, storage), checkpointer=saver
            )
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            state = CampaignState.model_validate((await graph.aget_state(config)).values)

        for direction in state.direction_set.directions:
            assert "FS-9" in direction.product_integration or "FS-9" in direction.big_idea
            # The brand's prohibition is carried into every direction.
            assert "indestructible" in direction.negative_constraints.forbidden_text
            # The IP boundary is stated per direction (ADR-011).
            assert direction.reference_characteristics_avoided


class TestCreativeGraphTenancy:
    async def test_another_organizations_campaign_cannot_enter_the_stage(
        self, session, workspace, storage, dsn
    ) -> None:
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _confirmed_campaign(session, theirs, their_brand)
        await session.commit()
        config = {"configurable": {"thread_id": creative_thread_id(str(their_campaign.id))}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            # Deps carry the attacker's organization.
            graph = build_creative_graph(
                _deps(session, workspace.org.id, storage), checkpointer=saver
            )
            with pytest.raises(PermissionError):
                await graph.ainvoke(
                    CampaignState(
                        campaign_id=str(their_campaign.id),
                        project_id=str(workspace.org.id),
                        user_id=str(workspace.user.id),
                    ),
                    config,
                )
