"""The campaign discovery graph.

The mandatory property: the interview survives a pause, a refresh and a fresh
process. These tests build a *new* graph object and a *new* checkpointer for
every resume, so nothing carries over in memory — only the Postgres checkpoint.
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.config import get_settings
from app.db.models import BrandProfileRow, CampaignRow
from app.domain.campaign import CampaignInputs
from app.domain.common import Channel
from app.graph.build import build_discovery_graph
from app.graph.nodes.deps import NodeDeps
from app.graph.serde import checkpointer_kwargs
from app.graph.state import CampaignState
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.mock.llm import MockLLMProvider
from tests.integration.factories import make_org

pytestmark = pytest.mark.integration

ANSWERS = [
    "This is a product launch.",
    "The FS-9 facade system.",
    "Architects and specifiers in Maharashtra.",
    "Engineered to outlast the building it clads.",
    "LinkedIn and Instagram post.",
]


@pytest.fixture
def dsn() -> str:
    return get_settings().database_url_sync.replace("/campaign_os", "/campaign_os_test")


async def _brand(session, org, name: str = "Northline") -> BrandProfileRow:
    row = BrandProfileRow(
        organization_id=org.id,
        name=name,
        payload={
            "id": str(uuid.uuid4()),
            "organization_id": str(org.id),
            "name": name,
            "audience_description": "Architects and contractors",
        },
    )
    session.add(row)
    await session.flush()
    return row


async def _campaign(session, org, brand) -> CampaignRow:
    campaign_id = uuid.uuid4()
    row = CampaignRow(
        id=campaign_id,
        organization_id=org.id,
        brand_profile_id=brand.id,
        title="Launch",
        status="DRAFT",
        thread_id=str(campaign_id),
        draft_inputs={},
    )
    session.add(row)
    await session.flush()
    return row


def _deps(session, org_id) -> NodeDeps:
    return NodeDeps(
        session=session,
        organization_id=org_id,
        llm=MockLLMProvider(),
        embeddings=MockEmbeddingProvider(),
        max_interview_turns=8,
    )


class TestInterruptAndResume:
    async def test_the_graph_runs_and_stops_at_the_first_question(
        self, session, workspace, dsn
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        await session.commit()

        config = {"configurable": {"thread_id": campaign.thread_id}}
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            result = await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            assert result.get("__interrupt__"), "the graph must pause for the first answer"
            snapshot = await graph.aget_state(config)
            assert snapshot.next == ("campaign_interviewer",)

    async def test_a_fresh_graph_and_saver_resume_the_same_conversation(
        self, session, workspace, dsn
    ) -> None:
        """The property the product depends on: after a refresh, discovery
        continues instead of starting over."""
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": campaign.thread_id}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )

        # Everything rebuilt: new saver, new graph object, nothing shared.
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            before = await graph.aget_state(config)
            assert before.next == ("campaign_interviewer",)

            await graph.ainvoke(Command(resume={"answer": ANSWERS[0]}), config)
            after = await graph.aget_state(config)
            state = CampaignState.model_validate(after.values)

        assert state.interview_turn_count == 1
        assert state.campaign_inputs.campaign_objective
        # The reply is in the transcript, not lost to the resume.
        assert any(t.role == "user" and ANSWERS[0] in t.content for t in state.conversation)

    async def test_state_accumulates_across_several_resumes(self, session, workspace, dsn) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": campaign.thread_id}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            for answer in ANSWERS:
                snapshot = await graph.aget_state(config)
                if not snapshot.next:
                    break
                await graph.ainvoke(Command(resume={"answer": answer}), config)

            final = CampaignState.model_validate((await graph.aget_state(config)).values)

        assert final.interview_turn_count >= 4
        # Conversation grew rather than being replaced — the append reducer
        # still behaves with msgpack and Postgres in the path.
        assert len(final.conversation) == final.interview_turn_count * 2

    async def test_a_completed_interview_produces_a_campaign_specification(
        self, session, workspace, dsn
    ) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": campaign.thread_id}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            for answer in ANSWERS + ["Request a specification pack."]:
                snapshot = await graph.aget_state(config)
                if not snapshot.next:
                    break
                await graph.ainvoke(Command(resume={"answer": answer}), config)
            final = CampaignState.model_validate((await graph.aget_state(config)).values)

        assert final.interview_complete is True
        assert final.campaign_brief is not None
        spec = final.campaign_brief
        assert spec.campaign_id == str(campaign.id)
        assert spec.objective and spec.audience and spec.product and spec.key_message
        # Provenance survived into the specification.
        assert spec.field_assertions

    async def test_brand_context_reaches_the_graph(self, session, workspace, dsn) -> None:
        brand = await _brand(session, workspace.org)
        campaign = await _campaign(session, workspace.org, brand)
        await session.commit()
        config = {"configurable": {"thread_id": campaign.thread_id}}

        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            await graph.ainvoke(
                CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(workspace.org.id),
                    user_id=str(workspace.user.id),
                ),
                config,
            )
            state = CampaignState.model_validate((await graph.aget_state(config)).values)

        assert state.brand is not None
        assert state.brand.name == "Northline"


class TestGraphTenancy:
    async def test_a_campaign_from_another_organization_cannot_be_run(
        self, session, workspace, dsn
    ) -> None:
        """Scope is enforced inside the graph too, not only at the API."""
        theirs = await make_org(session)
        their_brand = await _brand(session, theirs, name="Competitor")
        their_campaign = await _campaign(session, theirs, their_brand)
        await session.commit()

        config = {"configurable": {"thread_id": their_campaign.thread_id}}
        async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
            # Deps carry the attacker's organization.
            graph = build_discovery_graph(_deps(session, workspace.org.id), checkpointer=saver)
            # PermissionError specifically: the scoped repository found
            # nothing, which is what `load_project` turns into a refusal.
            with pytest.raises(PermissionError):
                await graph.ainvoke(
                    CampaignState(
                        campaign_id=str(their_campaign.id),
                        project_id=str(workspace.org.id),
                        user_id=str(workspace.user.id),
                    ),
                    config,
                )


class TestSpecificationCompilation:
    async def test_a_human_edited_field_survives_recompilation(self, session, workspace) -> None:
        """Recompiling must never quietly undo an edit."""
        from app.domain.campaign import (
            Availability,
            CampaignBrief,
            Certainty,
            FieldAssertion,
        )
        from app.graph.nodes.discovery import build_campaign_specification

        edited = FieldAssertion(
            field="key_message",
            availability=Availability.KNOWN,
            certainty=Certainty.STATED,
            edited_by_human=True,
        )
        previous = CampaignBrief(
            campaign_id="c1",
            title="T",
            objective="launch",
            audience="architects",
            product="FS-9",
            key_message="A human wrote this",
            cta="Learn more",
            channels=[Channel.LINKEDIN],
            field_assertions={"key_message": edited},
        )
        state = CampaignState(
            campaign_id="c1",
            project_id="p1",
            user_id="u1",
            campaign_brief=previous,
            campaign_inputs=CampaignInputs(
                campaign_objective="launch",
                product="FS-9",
                target_audience="architects",
                key_message="the model would have written this",
                channels=[Channel.LINKEDIN],
            ),
        )
        node = build_campaign_specification(_deps(session, workspace.org.id))
        result = await node(state)

        assert result["campaign_brief"].key_message == "A human wrote this"
        assert result["campaign_brief"].version == previous.version + 1
