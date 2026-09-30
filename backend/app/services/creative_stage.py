"""Creative stage orchestration.

The seam between HTTP and the Milestone 5 graph: starting the stage, answering
each gate, and projecting graph state into the application tables the UI reads
(ADR-004 — the checkpoint is execution state, not product state).

Runs on a thread derived from the campaign row, never from a request
parameter (M1_SECURITY_AUDIT A-5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import CampaignRow
from app.domain.approval import Decision, Gate
from app.domain.campaign import CampaignBrief
from app.domain.common import Channel
from app.domain.creative import (
    CreativeDirectionSet,
    CreativeRevisionDelta,
    CreativeSpecification,
    DiversityVerdict,
)
from app.domain.workspace import Principal
from app.errors import Conflict, NotFound, ValidationFailed
from app.graph.build import build_creative_graph, creative_thread_id
from app.graph.nodes.creative import GATE_KIND_BY_NODE
from app.graph.nodes.deps import NodeDeps
from app.graph.state import CampaignState
from app.logging import get_logger
from app.providers.base import EmbeddingProvider, LLMProvider, StorageProvider
from app.repositories.creative import (
    CreativeApprovalRepository,
    CreativeDirectionSetRepository,
    CreativeRevisionRepository,
    CreativeSpecificationRepository,
)
from app.services.campaigns import checkpointer_for

log = get_logger(__name__)

#: Discovery must be finished and confirmed before the creative stage starts.
REQUIRED_CAMPAIGN_STATUS = "SPECIFICATION_CONFIRMED"

_NO_INVOKE = object()


@dataclass(frozen=True)
class CreativeTurn:
    """What the UI needs after starting the stage or answering a gate."""

    campaign_id: str
    gate: str | None
    direction_set: CreativeDirectionSet | None
    selected_direction_id: str | None
    specification: CreativeSpecification | None
    diversity: DiversityVerdict | None
    approved: bool
    gaps: list[str]
    #: The channels the Campaign Specification declares. The only channels a
    #: per-channel copy override may name — offering one the campaign does not
    #: run, and then refusing the save, would be a worse way to say the same.
    channels: list[Channel] = field(default_factory=list)


class CreativeStageService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        settings: Settings,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
        storage: StorageProvider,
    ) -> None:
        self.session = session
        self.principal = principal
        self.settings = settings
        self.organization_id = uuid.UUID(principal.organization_id)
        self.deps = NodeDeps(
            session=session,
            organization_id=self.organization_id,
            llm=llm,
            embeddings=embeddings,
            storage=storage,
            max_interview_turns=settings.max_interview_turns,
        )
        self.direction_sets = CreativeDirectionSetRepository(session, self.organization_id)
        self.specifications = CreativeSpecificationRepository(session, self.organization_id)
        self.approvals = CreativeApprovalRepository(session, self.organization_id)
        self.revisions = CreativeRevisionRepository(session, self.organization_id)

    # ----------------------------------------------------------------- entry
    async def _campaign(self, campaign_id: uuid.UUID) -> CampaignRow:
        from app.repositories.campaigns import CampaignRepository

        row = await CampaignRepository(self.session, self.organization_id).get(campaign_id)
        if row is None:
            raise NotFound("Campaign not found.")
        return row

    async def start(self, campaign_id: uuid.UUID) -> CreativeTurn:
        """Begin, or re-enter, the creative stage."""
        campaign = await self._campaign(campaign_id)
        if campaign.status != REQUIRED_CAMPAIGN_STATUS:
            raise Conflict("Confirm the Campaign Specification before starting creative work.")
        return await self._advance(campaign, resume=None)

    async def decide_strategy(
        self,
        campaign_id: uuid.UUID,
        *,
        decision: Decision,
        direction_id: str | None,
        feedback: str | None,
    ) -> CreativeTurn:
        """Gate 1."""
        if decision is Decision.APPROVE and not direction_id:
            raise ValidationFailed(
                "Choose a direction to approve.", details={"field": "direction_id"}
            )
        campaign = await self._campaign(campaign_id)
        await self.approvals.record(
            campaign_id=campaign.id,
            gate=Gate.STRATEGY.value,
            decision=decision.value,
            target_id=uuid.UUID(direction_id) if direction_id else None,
            feedback=feedback,
            decided_by=uuid.UUID(self.principal.user.id),
        )
        return await self._advance(
            campaign,
            resume={
                "decision": decision.value,
                "target_id": direction_id,
                "feedback": feedback,
            },
        )

    async def decide_specification(
        self, campaign_id: uuid.UUID, *, decision: Decision, feedback: str | None
    ) -> CreativeTurn:
        """Gate 2. Approval ends Milestone 5 — nothing is generated."""
        campaign = await self._campaign(campaign_id)
        await self.approvals.record(
            campaign_id=campaign.id,
            gate=Gate.SPECIFICATION.value,
            decision=decision.value,
            target_id=None,
            feedback=feedback,
            decided_by=uuid.UUID(self.principal.user.id),
        )
        return await self._advance(
            campaign, resume={"decision": decision.value, "feedback": feedback}
        )

    # ------------------------------------------------------------- execution
    async def _advance(
        self, campaign: CampaignRow, *, resume: dict[str, Any] | None
    ) -> CreativeTurn:
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}

        async with checkpointer_for(self.settings) as saver:
            graph = build_creative_graph(self.deps, checkpointer=saver)
            existing = await graph.aget_state(config)

            payload: Any
            if resume is not None:
                payload = Command(resume=resume)
            elif existing.values:
                # Re-entering: report where the stage is rather than re-running
                # it. Re-invoking would reset the conversation, exactly as it
                # would in discovery.
                payload = _NO_INVOKE
            elif await self.direction_sets.latest(campaign.id) is not None:
                # Re-entering a campaign whose creative exists in the tables but
                # not in a checkpoint. Same answer as above for the same reason,
                # and the check has to be separate because `existing.values`
                # cannot see a row: a set written by anything other than this
                # process's own graph run — the benchmark seed, a restore, a
                # future importer — leaves the checkpoint empty.
                #
                # Running the Creative Director here would produce a second
                # version 1 and `_project` would write it over the first, which
                # is how one click replaced an approved, human-decided direction
                # set with fresh model output. Refusing to start is the whole
                # fix; `_from_rows` then reports what is actually there.
                log.info(
                    "creative_reentry_from_rows",
                    campaign_id=str(campaign.id),
                    reason="direction set exists without a checkpoint",
                )
                return await self._from_rows(campaign)
            else:
                payload = CampaignState(
                    campaign_id=str(campaign.id),
                    project_id=str(campaign.project_id or campaign.organization_id),
                    user_id=self.principal.user.id,
                )

            try:
                if payload is not _NO_INVOKE:
                    await graph.ainvoke(payload, config)
            except Exception as exc:  # noqa: BLE001 - recorded, never raised raw
                log.exception("creative_graph_failed", campaign_id=str(campaign.id))
                raise ValidationFailed(
                    "Creative work could not continue. Please try again."
                ) from exc
            snapshot = await graph.aget_state(config)

        return await self._project(campaign, snapshot)

    async def _project(self, campaign: CampaignRow, snapshot: Any) -> CreativeTurn:
        """Copy graph state into application tables the UI reads."""
        values = snapshot.values
        state = (
            values if isinstance(values, CampaignState) else CampaignState.model_validate(values)
        )

        if state.direction_set is not None:
            await self.direction_sets.upsert_version(
                campaign_id=campaign.id,
                version=state.direction_set.version,
                payload=state.direction_set.model_dump(mode="json"),
                selected_direction_id=(
                    uuid.UUID(state.selected_direction.id) if state.selected_direction else None
                ),
            )
        if state.creative_revision is not None:
            await self.revisions.record(
                campaign_id=campaign.id,
                iteration=state.creative_revision.iteration,
                delta=state.creative_revision.model_dump(mode="json"),
                from_version=state.creative_revision.iteration,
                to_version=state.creative_revision.iteration + 1,
            )
        if state.creative_specification is not None:
            await self.specifications.upsert_version(
                campaign_id=campaign.id,
                version=state.creative_specification.version,
                direction_id=uuid.UUID(state.creative_specification.direction_id),
                payload=state.creative_specification.model_dump(mode="json"),
            )

        approved = (
            state.approval_states.get(Gate.SPECIFICATION.value) is not None
            and state.approval_states[Gate.SPECIFICATION.value].decision is Decision.APPROVE
        )
        if approved:
            latest = await self.specifications.latest(campaign.id)
            if latest is not None and latest.approved_at is None:
                await self.specifications.approve(latest, user_id=uuid.UUID(self.principal.user.id))

        return CreativeTurn(
            campaign_id=str(campaign.id),
            gate=_pending_gate_kind(snapshot),
            direction_set=state.direction_set,
            selected_direction_id=(
                state.selected_direction.id if state.selected_direction else None
            ),
            specification=state.creative_specification,
            diversity=state.direction_set.diversity if state.direction_set else None,
            approved=approved,
            gaps=state.creative_context.gaps if state.creative_context else [],
            channels=await self._declared_channels(campaign.id),
        )

    # ------------------------------------------------------- human edits
    async def edit_specification(
        self, campaign_id: uuid.UUID, edits: dict[str, Any]
    ) -> CreativeSpecification:
        """Apply human edits and mark them, so regeneration cannot undo them.

        Written into graph state as well as the database: storing them only in
        the database would leave the builder holding the pre-edit version.
        """
        campaign = await self._campaign(campaign_id)
        latest = await self.specifications.latest(campaign.id)
        if latest is None:
            raise NotFound("This campaign has no creative specification yet.")
        if latest.approved_at is not None:
            raise Conflict("This specification is approved. Reopen it to make changes.")

        current = CreativeSpecification.model_validate(latest.payload)
        data = current.model_dump(mode="json")
        editable = set(CreativeSpecification.model_fields) - {
            "id",
            "campaign_id",
            "direction_id",
            "version",
            "human_edited_fields",
        }
        touched = [f for f in edits if f in editable]
        if not touched:
            raise ValidationFailed("Nothing to update.", details={"field": "body"})
        if "channel_copy" in touched:
            await self._assert_declared_channels(campaign.id, edits["channel_copy"])
        for name in touched:
            data[name] = edits[name]
        data["human_edited_fields"] = sorted(set(current.human_edited_fields) | set(touched))
        data["version"] = current.version + 1

        updated = CreativeSpecification.model_validate(data)
        await self.specifications.upsert_version(
            campaign_id=campaign.id,
            version=updated.version,
            direction_id=uuid.UUID(updated.direction_id),
            payload=updated.model_dump(mode="json"),
        )

        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}
        async with checkpointer_for(self.settings) as saver:
            graph = build_creative_graph(self.deps, checkpointer=saver)
            if (await graph.aget_state(config)).values:
                await graph.aupdate_state(config, {"creative_specification": updated})
        return updated

    async def _declared_channels(self, campaign_id: uuid.UUID) -> list[Channel]:
        """The channels the Campaign Specification names, or none when it has
        not been confirmed yet."""
        from app.repositories.campaigns import CampaignSpecificationRepository

        row = await CampaignSpecificationRepository(self.session, self.organization_id).latest(
            campaign_id
        )
        if row is None:
            return []
        return list(CampaignBrief.model_validate(row.payload).channels)

    async def _assert_declared_channels(self, campaign_id: uuid.UUID, overrides: Any) -> None:
        """Per-channel copy only for channels this campaign actually runs.

        The Campaign Specification owns the channel list; the Creative
        Specification does not, and cannot check this for itself. Refused
        rather than trimmed: an override silently dropped is words a user wrote
        and believes are live.
        """
        channels = await self._declared_channels(campaign_id)
        if not channels:
            raise Conflict("Confirm the Campaign Specification before writing per-channel copy.")

        declared = {c.value for c in channels}
        asked = {str(key) for key in (overrides or {})}
        undeclared = sorted(asked - declared)
        if undeclared:
            raise ValidationFailed(
                f"This campaign does not run {', '.join(undeclared)}. "
                f"Its channels are {', '.join(sorted(declared))}.",
                details={"field": "channel_copy", "channels": sorted(declared)},
            )

    async def current(self, campaign_id: uuid.UUID) -> CreativeTurn:
        """Read-only view of where the creative stage stands."""
        campaign = await self._campaign(campaign_id)
        config = {"configurable": {"thread_id": creative_thread_id(str(campaign.id))}}
        async with checkpointer_for(self.settings) as saver:
            graph = build_creative_graph(self.deps, checkpointer=saver)
            snapshot = await graph.aget_state(config)
        if not snapshot.values:
            return await self._from_rows(campaign)
        return await self._project(campaign, snapshot)

    async def _from_rows(self, campaign: CampaignRow) -> CreativeTurn:
        """The stage as the application tables record it, with no checkpoint.

        `_project` exists to copy graph state *into* these tables because they
        are what the UI reads (ADR-004: the checkpoint is execution state, not
        product state). Reading them back when there is no execution state is
        the same direction of flow, not a second source of truth — the rows are
        the product state either way, and nothing here writes.

        It matters because a campaign's creative work can be real without this
        process ever having run the graph for it: the hyperlocal benchmark
        writes an approved Creative Direction set and an approved Creative
        Specification through the repositories (`scripts/seed_benchmark.py`),
        deliberately stopping before generation. Reporting those campaigns as
        having no creative at all told the reader the opposite of what the
        database says, and offered to build routes that already existed.

        Two fields cannot come from rows, and are reported as absent rather
        than guessed:

        * `gate` is `None`. A gate is open when the graph is parked on its node
          (`_pending_gate_kind`); with no execution there is nothing parked and
          nothing for a human to answer. Reporting one would draw an Approve
          button whose resume has no checkpoint to resume.
        * `gaps` is empty. `CreativeContext` is assembled inside the run and
          has no table, so a gap list here would be invented.
        """
        direction_row = await self.direction_sets.latest(campaign.id)
        specification_row = await self.specifications.latest(campaign.id)
        direction_set = (
            CreativeDirectionSet.model_validate(direction_row.payload)
            if direction_row is not None
            else None
        )
        specification = (
            CreativeSpecification.model_validate(specification_row.payload)
            if specification_row is not None
            else None
        )
        return CreativeTurn(
            campaign_id=str(campaign.id),
            gate=None,
            direction_set=direction_set,
            selected_direction_id=(
                str(direction_row.selected_direction_id)
                if direction_row is not None and direction_row.selected_direction_id is not None
                else None
            ),
            specification=specification,
            diversity=direction_set.diversity if direction_set is not None else None,
            approved=specification_row is not None and specification_row.approved_at is not None,
            gaps=[],
            channels=await self._declared_channels(campaign.id),
        )


def _pending_gate_kind(snapshot: Any) -> str | None:
    """Which human gate is open, if any.

    The live interrupt payload is the first source. It is not the only one:
    writing to state with `aupdate_state` — which is how a human edit reaches
    the graph — starts a new checkpoint where the gate node has not run yet, so
    its interrupt has not re-materialised. The node is still the one the graph
    is parked on and will interrupt again on the next step, so a gate node in
    `next` means that gate is open. Reading only the payload left an edited
    specification with no gate and no approval — stranded.
    """
    for task in getattr(snapshot, "tasks", ()) or ():
        for item in getattr(task, "interrupts", ()) or ():
            payload = getattr(item, "value", None)
            if isinstance(payload, dict) and "kind" in payload:
                return str(payload["kind"])
    for node in getattr(snapshot, "next", ()) or ():
        kind = GATE_KIND_BY_NODE.get(str(node))
        if kind is not None:
            return kind
    return None


def protected_facts_preserved(before: CreativeDirectionSet, delta: CreativeRevisionDelta) -> bool:
    """Every protected campaign fact is on the KEEP list."""
    from app.domain.creative import PROTECTED_CAMPAIGN_FACTS

    return set(PROTECTED_CAMPAIGN_FACTS) <= set(delta.keep)
