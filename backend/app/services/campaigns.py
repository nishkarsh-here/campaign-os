"""Campaign discovery orchestration.

Owns the seam between HTTP and the graph: starting a run, resuming one with a
user's answer, and projecting graph state into the application tables the UI
reads (ADR-004 — the checkpoint is execution state, not product state).

The `thread_id` always comes from a scope-checked campaign row. Deriving it
from a request parameter would resume another tenant's execution, because the
checkpointer has no concept of an organization (M1_SECURITY_AUDIT A-5).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import CampaignRow
from app.domain.campaign import CampaignBrief, CampaignInputs, InterviewQuestion
from app.domain.common import CampaignRecordStatus
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound, ValidationFailed
from app.graph.build import build_discovery_graph
from app.graph.nodes.deps import NodeDeps
from app.graph.serde import checkpointer_kwargs
from app.graph.state import CampaignState
from app.logging import get_logger
from app.providers.base import EmbeddingProvider, LLMProvider
from app.repositories.brands import BrandRepository
from app.repositories.campaigns import (
    CampaignMessageRepository,
    CampaignRepository,
    CampaignRunRepository,
    CampaignSpecificationRepository,
)

log = get_logger(__name__)

#: Sentinel: an existing thread is read, never re-invoked.
_NO_INVOKE = object()

#: The row lifecycle, from the one enum the database check constraint is also
#: generated from (`CampaignRecordStatus`). Bare strings here is how the column
#: and the domain came to disagree in the first place.
STATUS_DRAFT = CampaignRecordStatus.DRAFT.value
STATUS_INTERVIEWING = CampaignRecordStatus.INTERVIEWING.value
STATUS_SPEC_READY = CampaignRecordStatus.SPECIFICATION_READY.value
STATUS_SPEC_CONFIRMED = CampaignRecordStatus.SPECIFICATION_CONFIRMED.value
STATUS_FAILED = CampaignRecordStatus.FAILED.value


@dataclass(frozen=True)
class DiscoveryTurn:
    """What the UI needs after starting or resuming the interview."""

    campaign_id: str
    status: str
    question: InterviewQuestion | None
    missing: list[str]
    turn: int
    interview_complete: bool
    specification: CampaignBrief | None
    inputs: CampaignInputs


@asynccontextmanager
async def checkpointer_for(settings: Settings) -> AsyncIterator[Any]:
    """A checkpointer built the only supported way — with the allowlist.

    Nothing may construct one without `checkpointer_kwargs()`, or a LangGraph
    upgrade would refuse our own domain types and break resume
    (M1_SECURITY_AUDIT A-2).

    **`setup()` is deliberately not called here.** It issues
    `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction and
    waits for every open transaction on the database to finish. Calling it
    per-request — while that request's own session already holds a transaction
    — deadlocks the request against itself. It belongs at startup, where no
    request transaction exists; see `ensure_checkpoint_tables`.
    """
    async with AsyncPostgresSaver.from_conn_string(
        settings.database_url_sync, **checkpointer_kwargs()
    ) as saver:
        yield saver


async def ensure_checkpoint_tables(settings: Settings) -> None:
    """Create the checkpointer's tables. Call once, at startup, never in a request."""
    async with checkpointer_for(settings) as saver:
        await saver.setup()


class CampaignDiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        settings: Settings,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
    ) -> None:
        self.session = session
        self.principal = principal
        self.settings = settings
        self.llm = llm
        self.embeddings = embeddings
        self.organization_id = uuid.UUID(principal.organization_id)
        self.campaigns = CampaignRepository(session, self.organization_id)
        self.messages = CampaignMessageRepository(session, self.organization_id)
        self.runs = CampaignRunRepository(session, self.organization_id)
        self.specifications = CampaignSpecificationRepository(session, self.organization_id)

    # ------------------------------------------------------------------ CRUD
    async def create(
        self, *, brand_id: uuid.UUID, title: str, project_id: uuid.UUID | None
    ) -> CampaignRow:
        """A campaign must name a brand this organization owns.

        The brand is resolved through the scoped repository, so selecting
        another organization's brand is indistinguishable from selecting one
        that does not exist.
        """
        brand = await BrandRepository(self.session, self.organization_id).get(brand_id)
        if brand is None:
            raise NotFound("Brand not found.")
        if project_id is not None:
            from app.repositories.projects import ProjectRepository

            if await ProjectRepository(self.session, self.organization_id).get(project_id) is None:
                raise NotFound("Project not found.")
        return await self.campaigns.create(
            brand_id=brand_id,
            title=title,
            project_id=project_id,
            created_by=uuid.UUID(self.principal.user.id),
        )

    async def get_row(self, campaign_id: uuid.UUID) -> CampaignRow:
        row = await self.campaigns.get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    # ------------------------------------------------------------- discovery
    async def start(self, campaign_id: uuid.UUID) -> DiscoveryTurn:
        """Begin the interview, or re-enter one already in progress.

        Re-entering must never re-send an initial state: LangGraph would merge
        it into the existing thread and reset every scalar, throwing away the
        turn count and the answers with it. An existing thread is therefore
        *read*, not re-invoked — which is what makes a browser refresh safe.
        """
        campaign = await self.get_row(campaign_id)
        if campaign.status == STATUS_SPEC_CONFIRMED:
            raise Conflict("This campaign's specification is already confirmed.")
        return await self._advance(campaign, resume=None)

    async def answer(self, campaign_id: uuid.UUID, reply: str) -> DiscoveryTurn:
        """Resume the paused interview with the user's reply."""
        if not reply.strip():
            raise ValidationFailed("Please write an answer.", details={"field": "answer"})
        campaign = await self.get_row(campaign_id)
        if campaign.status == STATUS_SPEC_CONFIRMED:
            raise Conflict("This campaign's specification is already confirmed.")
        return await self._advance(campaign, resume={"answer": reply.strip()})

    async def _advance(
        self, campaign: CampaignRow, *, resume: dict[str, str] | None
    ) -> DiscoveryTurn:
        run = await self.runs.start(campaign.id)
        deps = NodeDeps(
            session=self.session,
            organization_id=self.organization_id,
            llm=self.llm,
            embeddings=self.embeddings,
            max_interview_turns=self.settings.max_interview_turns,
        )
        # thread_id from the scope-checked row, never from the request.
        config = {"configurable": {"thread_id": campaign.thread_id}}

        async with checkpointer_for(self.settings) as saver:
            graph = build_discovery_graph(deps, checkpointer=saver)
            existing = await graph.aget_state(config)
            payload: Any
            if resume is not None:
                payload = Command(resume=resume)
            elif existing.values:
                # The thread already exists. Report where it is rather than
                # re-running it — re-invoking would reset the conversation.
                payload = _NO_INVOKE
            else:
                payload = CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(campaign.project_id or campaign.organization_id),
                    user_id=self.principal.user.id,
                    campaign_inputs=CampaignInputs.model_validate(campaign.draft_inputs or {}),
                )
            try:
                if payload is not _NO_INVOKE:
                    await graph.ainvoke(payload, config)
            except Exception as exc:  # noqa: BLE001 - a failed run is recorded, not raised raw
                log.exception("campaign_graph_failed", campaign_id=str(campaign.id))
                await self.runs.finish(
                    run, status="FAILED", error="Discovery could not continue. Please try again."
                )
                await self.campaigns.set_status(campaign, STATUS_FAILED)
                raise ValidationFailed("Discovery could not continue. Please try again.") from exc
            snapshot = await graph.aget_state(config)

        return await self._project(campaign, run, snapshot)

    async def _project(self, campaign: CampaignRow, run: Any, snapshot: Any) -> DiscoveryTurn:
        """Copy graph state into application tables (ADR-004).

        The UI reads these rows; it never reads the checkpoint.
        """
        values = snapshot.values
        state = (
            values if isinstance(values, CampaignState) else CampaignState.model_validate(values)
        )
        pending = _pending_question(snapshot)

        await self.campaigns.save_draft_inputs(
            campaign, state.campaign_inputs.model_dump(mode="json")
        )

        # Mirror the transcript so it is queryable without the checkpoint.
        existing = len(await self.messages.list_for_campaign(campaign.id))
        for turn in list(state.conversation)[existing:]:
            await self.messages.append(
                campaign_id=campaign.id,
                role=turn.role,
                content=turn.content,
                targets_field=turn.targets_field,
            )

        specification = state.campaign_brief
        if specification is not None:
            latest = await self.specifications.latest(campaign.id)
            payload = specification.model_dump(mode="json")
            if latest is None or latest.payload != payload:
                await self.specifications.create_version(campaign_id=campaign.id, payload=payload)
            status = STATUS_SPEC_READY
        else:
            status = STATUS_INTERVIEWING

        if campaign.status != STATUS_SPEC_CONFIRMED:
            await self.campaigns.set_status(campaign, status)
        await self.runs.finish(
            run,
            status="WAITING_HUMAN" if pending else "COMPLETED",
            current_node=list(snapshot.next)[0] if snapshot.next else None,
        )

        return DiscoveryTurn(
            campaign_id=str(campaign.id),
            status=campaign.status,
            question=pending,
            missing=_missing(snapshot),
            turn=state.interview_turn_count,
            interview_complete=state.interview_complete,
            specification=specification,
            inputs=state.campaign_inputs,
        )

    # ---------------------------------------------------- specification edits
    async def update_specification(
        self, campaign_id: uuid.UUID, edits: dict[str, Any]
    ) -> CampaignBrief:
        """Apply human edits, and mark them so recompilation cannot undo them.

        The edited specification is written back into graph state as well as
        the database. Storing it only in the database would leave the graph
        holding the pre-edit version, and the next recompilation would happily
        overwrite the human's work — the preservation has to be real, not
        incidental.
        """
        campaign = await self.get_row(campaign_id)
        latest = await self.specifications.latest(campaign.id)
        if latest is None:
            raise NotFound("This campaign has no specification yet.")
        if campaign.status == STATUS_SPEC_CONFIRMED:
            raise Conflict("This specification is confirmed. Reopen it to make changes.")

        from app.domain.campaign import Availability, Certainty, FieldAssertion

        current = CampaignBrief.model_validate(latest.payload)
        data = current.model_dump(mode="json")
        assertions = dict(current.field_assertions)

        editable = set(CampaignBrief.model_fields) - {
            "id",
            "campaign_id",
            "version",
            "field_assertions",
        }
        touched = False
        for field, value in edits.items():
            if field not in editable:
                continue
            data[field] = value
            assertions[field] = FieldAssertion(
                field=field,
                availability=Availability.KNOWN,
                certainty=Certainty.STATED,
                source="you edited this",
                edited_by_human=True,
            )
            touched = True
        if not touched:
            raise ValidationFailed("Nothing to update.", details={"field": "body"})

        data["field_assertions"] = {k: v.model_dump(mode="json") for k, v in assertions.items()}
        data["version"] = current.version + 1
        updated = CampaignBrief.model_validate(data)
        await self.specifications.create_version(
            campaign_id=campaign.id, payload=updated.model_dump(mode="json")
        )

        config = {"configurable": {"thread_id": campaign.thread_id}}
        async with checkpointer_for(self.settings) as saver:
            deps = NodeDeps(
                session=self.session,
                organization_id=self.organization_id,
                llm=self.llm,
                embeddings=self.embeddings,
                max_interview_turns=self.settings.max_interview_turns,
            )
            graph = build_discovery_graph(deps, checkpointer=saver)
            if (await graph.aget_state(config)).values:
                await graph.aupdate_state(config, {"campaign_brief": updated})
        return updated

    async def confirm_specification(self, campaign_id: uuid.UUID) -> CampaignBrief:
        """The explicit human act that closes discovery.

        Milestone 3 stops here: nothing creative runs on confirmation.
        """
        campaign = await self.get_row(campaign_id)
        latest = await self.specifications.latest(campaign.id)
        if latest is None:
            raise NotFound("This campaign has no specification yet.")
        await self.specifications.confirm(latest, user_id=uuid.UUID(self.principal.user.id))
        await self.campaigns.set_status(campaign, STATUS_SPEC_CONFIRMED)
        return CampaignBrief.model_validate(latest.payload)


def _pending_question(snapshot: Any) -> InterviewQuestion | None:
    """The question the graph is paused on, if any."""
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            payload = getattr(item, "value", None)
            if isinstance(payload, dict) and payload.get("kind") == "interview_question":
                return InterviewQuestion.model_validate(payload["question"])
    return None


def _missing(snapshot: Any) -> list[str]:
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            payload = getattr(item, "value", None)
            if isinstance(payload, dict) and "missing" in payload:
                return list(payload["missing"])
    return []
