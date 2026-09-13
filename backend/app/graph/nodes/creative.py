"""Milestone 5 creative nodes.

    load_creative_context -> creative_director -> [GATE 1] ->
    creative_specification_builder -> [GATE 2] -> END

Two interrupts, both resumable from the Postgres checkpoint exactly as the
discovery gates are.

`load_creative_context` reuses the Milestone 4 `CreativeContextService` rather
than assembling anything itself — the whole point of that service is that the
director does not re-derive brand rules or re-weight preferences.
"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.types import interrupt

from app.domain.common import CampaignStatus, ErrorSeverity, ExecutionError
from app.domain.creative import (
    PROTECTED_CAMPAIGN_FACTS,
    CreativeRevisionDelta,
)
from app.graph.nodes.deps import NodeDeps
from app.graph.state import CampaignState
from app.logging import get_logger
from app.providers.base import ProviderError
from app.services.creative_director import CreativeDirector

log = get_logger(__name__)

Node = Any


def load_creative_context(deps: NodeDeps) -> Node:
    """Assemble brand + specification + reference DNA + preferences."""

    async def node(state: CampaignState) -> dict[str, Any]:
        from app.repositories.campaigns import CampaignRepository
        from app.services.creative_context import CreativeContextService

        campaigns = CampaignRepository(deps.session, deps.organization_id)
        campaign = await campaigns.get(uuid.UUID(state.campaign_id))
        if campaign is None:
            # Scoped lookup: another organization's campaign resolves to nothing.
            raise PermissionError("Campaign not found in this organization.")

        if deps.storage is None:
            # The creative stage always reads reference bytes; a bundle without
            # storage is a wiring mistake, not a runtime condition to tolerate.
            raise RuntimeError("load_creative_context requires a storage provider")

        service = CreativeContextService(
            deps.session,
            deps.organization_id,
            storage=deps.storage,
            llm=deps.llm,
            embeddings=deps.embeddings,
        )
        context = await service.build(campaign)

        errors: list[ExecutionError] = []
        if not context.is_ready():
            # Degrade, do not stop: the gaps are named and the director is
            # told not to invent them.
            errors.append(
                ExecutionError(
                    node="load_creative_context",
                    severity=ErrorSeverity.WARNING,
                    code="CREATIVE_CONTEXT_INCOMPLETE",
                    message="; ".join(context.gaps) or "The creative context is incomplete.",
                )
            )
        return {
            "creative_context": context,
            "errors": errors,
            "status": CampaignStatus.STRATEGY,
        }

    return node


def creative_director(deps: NodeDeps) -> Node:
    """Three distinct strategic directions, or a typed failure."""

    async def node(state: CampaignState) -> dict[str, Any]:
        context = state.creative_context
        if context is None:
            raise RuntimeError("creative_director ran without a creative context")

        version = (state.direction_set.version + 1) if state.direction_set else 1
        director = CreativeDirector(deps.llm)
        try:
            outcome = await director.propose_directions(
                context, version=version, revision=state.creative_revision
            )
        except ProviderError as exc:
            # Malformed or failed model output is an execution error, never a
            # silently-dropped field (AI OUTPUT VALIDATION).
            log.warning("creative_directions_failed", detail=exc.detail)
            raise

        if not outcome.diversity.passed:
            log.info(
                "creative_directions_shipped_with_collisions",
                similarity=outcome.diversity.weakest_pair_similarity,
            )
        return {
            "direction_set": outcome.direction_set,
            "status": CampaignStatus.AWAITING_APPROVAL,
        }

    return node


#: Interrupt payload kinds, and the node each gate parks on. The API reports
#: an open gate by kind, so these two facts must stay together.
STRATEGY_GATE_KIND = "strategy_gate"
SPECIFICATION_GATE_KIND = "specification_gate"
GATE_KIND_BY_NODE: dict[str, str] = {
    "human_strategy_approval": STRATEGY_GATE_KIND,
    "human_specification_approval": SPECIFICATION_GATE_KIND,
}


def human_strategy_approval(deps: NodeDeps) -> Node:
    """GATE 1 — the human picks a direction, rejects, or asks for changes."""

    async def node(state: CampaignState) -> dict[str, Any]:
        from app.domain.approval import ApprovalDecision, Decision, Gate, PendingGate

        direction_set = state.direction_set
        if direction_set is None:
            raise RuntimeError("strategy gate reached with no directions")

        payload = PendingGate(
            gate=Gate.STRATEGY,
            options=[Decision.APPROVE, Decision.REJECT, Decision.REQUEST_REVISION],
            prompt_text="Which direction should we take?",
            payload={
                "directions": [d.model_dump(mode="json") for d in direction_set.directions],
                "recommended_ordinal": direction_set.recommended_ordinal,
                "recommendation_reasons": direction_set.recommendation_reasons,
                "diversity": (
                    direction_set.diversity.model_dump(mode="json")
                    if direction_set.diversity
                    else None
                ),
                "version": direction_set.version,
            },
        )
        answer = interrupt({"kind": STRATEGY_GATE_KIND, **payload.model_dump(mode="json")})
        reply = answer if isinstance(answer, dict) else {}

        decision = Decision(reply.get("decision", Decision.APPROVE.value))
        feedback = reply.get("feedback") or None
        target = reply.get("target_id")

        record = ApprovalDecision(
            gate=Gate.STRATEGY, decision=decision, target_id=target, feedback=feedback
        )
        update: dict[str, Any] = {
            "approval_states": {Gate.STRATEGY.value: record},
            "pending_gate": None,
            "user_feedback": feedback,
            "status": CampaignStatus.STRATEGY,
        }

        if decision is Decision.APPROVE:
            chosen = (
                direction_set.by_id(target)
                if target
                else direction_set.by_ordinal(direction_set.recommended_ordinal or 1)
            )
            if chosen is None:
                raise ValueError("The approved direction is not in this set.")
            update["selected_direction"] = chosen
            update["creative_revision"] = None
        else:
            # Reject and revise both regenerate — the difference is only
            # whether the human named what to change.
            update["creative_revision"] = _revision_delta(state, feedback, target)
        return update

    return node


def _revision_delta(
    state: CampaignState, feedback: str | None, target: str | None
) -> CreativeRevisionDelta:
    """Turn feedback into an explicit KEEP/CHANGE record.

    The KEEP list is not negotiable: "make it more aspirational" must not
    change the product, the audience, or an approved claim. Those facts are
    listed as kept regardless of what the feedback says.
    """
    ordinal: int | None = None
    if target and state.direction_set is not None:
        chosen = state.direction_set.by_id(target)
        ordinal = chosen.ordinal if chosen else None

    iteration = (state.direction_set.version if state.direction_set else 0) or 1
    return CreativeRevisionDelta(
        iteration=iteration,
        feedback=feedback or "Not specified.",
        interpretation=("Keep the campaign facts; change the creative angle and its execution."),
        keep=list(PROTECTED_CAMPAIGN_FACTS),
        change=["emotional_angle", "visual_story", "subject", "environment", "lighting"],
        target_ordinal=ordinal,
    )


def creative_specification_builder(deps: NodeDeps) -> Node:
    """The execution plan for the approved direction."""

    async def node(state: CampaignState) -> dict[str, Any]:
        context = state.creative_context
        direction = state.selected_direction
        if context is None or direction is None:
            raise RuntimeError("specification builder ran without an approved direction")

        previous = state.creative_specification
        version = (previous.version + 1) if previous else 1
        director = CreativeDirector(deps.llm)
        specification = await director.build_specification(
            context, direction, version=version, previous=previous
        )
        return {
            "creative_specification": specification,
            "status": CampaignStatus.AWAITING_APPROVAL,
        }

    return node


def human_specification_approval(deps: NodeDeps) -> Node:
    """GATE 2 — the human approves, edits, or asks for changes to the plan."""

    async def node(state: CampaignState) -> dict[str, Any]:
        from app.domain.approval import ApprovalDecision, Decision, Gate, PendingGate

        specification = state.creative_specification
        if specification is None:
            raise RuntimeError("specification gate reached with no specification")

        payload = PendingGate(
            gate=Gate.SPECIFICATION,
            options=[Decision.APPROVE, Decision.EDIT, Decision.REQUEST_REVISION],
            prompt_text="Is this execution plan right?",
            payload={"specification": specification.model_dump(mode="json")},
        )
        answer = interrupt({"kind": SPECIFICATION_GATE_KIND, **payload.model_dump(mode="json")})
        reply = answer if isinstance(answer, dict) else {}

        decision = Decision(reply.get("decision", Decision.APPROVE.value))
        feedback = reply.get("feedback") or None
        record = ApprovalDecision(
            gate=Gate.SPECIFICATION,
            decision=decision,
            target_id=specification.id,
            feedback=feedback,
        )
        return {
            "approval_states": {Gate.SPECIFICATION.value: record},
            "pending_gate": None,
            "user_feedback": feedback,
            "status": (
                CampaignStatus.COMPLETED
                if decision is Decision.APPROVE
                else CampaignStatus.REVISING
            ),
        }

    return node
