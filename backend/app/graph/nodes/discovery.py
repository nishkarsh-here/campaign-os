"""Milestone 3 discovery nodes.

    load_project -> load_brand_brain -> campaign_interviewer -> [interrupt]
                                              |                      |
                                              +-- sufficient --> campaign_brief_builder

Each node returns only the keys its `NodeContract` declares. The interviewer is
the interrupt point: it asks one question, pauses, and resumes with the user's
reply — which is why the conversation survives a refresh or a restart.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import interrupt

from app.domain.brand import BrandKnowledge
from app.domain.campaign import (
    Availability,
    CampaignBrief,
    CampaignInputs,
    Certainty,
    ConversationTurn,
    FieldAssertion,
)
from app.domain.common import CampaignStatus, ErrorSeverity, ExecutionError
from app.domain.workspace import Organization, Project, User
from app.graph.nodes.deps import NodeDeps
from app.graph.state import CampaignState
from app.logging import get_logger
from app.providers.base import ProviderError
from app.services.brand_knowledge import BrandKnowledgeRetriever
from app.services.brands import row_to_profile
from app.services.campaign_interviewer import (
    FIELDS_BY_NAME,
    CampaignInterviewer,
    apply_updates,
    is_sufficient,
)

log = get_logger(__name__)

Node = Callable[[CampaignState], Awaitable[dict[str, Any]]]


def load_project(deps: NodeDeps) -> Node:
    """Resolve tenancy scope. Fatal: nothing may run without it."""

    async def node(state: CampaignState) -> dict[str, Any]:
        from app.db.models import CampaignRow
        from app.repositories.campaigns import CampaignRepository
        from app.repositories.organizations import OrganizationRepository, UserRepository

        campaigns = CampaignRepository(deps.session, deps.organization_id)
        campaign: CampaignRow | None = await campaigns.get(uuid.UUID(state.campaign_id))
        if campaign is None:
            # Scoped lookup: another organization's campaign resolves to nothing.
            raise PermissionError("Campaign not found in this organization.")

        org_row = await OrganizationRepository(deps.session, deps.organization_id).current()
        user_row = await UserRepository(deps.session).get(uuid.UUID(state.user_id))

        project = None
        if campaign.project_id is not None:
            from app.repositories.projects import ProjectRepository

            row = await ProjectRepository(deps.session, deps.organization_id).get(
                campaign.project_id
            )
            if row is not None:
                project = Project(
                    id=str(row.id),
                    organization_id=str(row.organization_id),
                    name=row.name,
                    description=row.description,
                )

        return {
            "organization": (
                Organization(id=str(org_row.id), name=org_row.name, slug=org_row.slug)
                if org_row
                else None
            ),
            "user": (
                User(id=str(user_row.id), email=user_row.email, display_name=user_row.display_name)
                if user_row
                else None
            ),
            "project": project,
            "status": CampaignStatus.INTERVIEWING,
        }

    return node


def load_brand_brain(deps: NodeDeps) -> Node:
    """Load the brand and a slice of its knowledge.

    Degrade-safe: a Brand Brain that cannot be retrieved must not stop a
    campaign, so a failure records a warning and the interview continues with
    the structured profile alone.
    """

    async def node(state: CampaignState) -> dict[str, Any]:
        from app.repositories.brands import BrandAssetRepository, BrandRepository
        from app.repositories.campaigns import CampaignRepository

        campaign = await CampaignRepository(deps.session, deps.organization_id).get(
            uuid.UUID(state.campaign_id)
        )
        if campaign is None:
            raise PermissionError("Campaign not found in this organization.")

        brand_row = await BrandRepository(deps.session, deps.organization_id).get(
            campaign.brand_profile_id
        )
        if brand_row is None:
            return {
                "errors": [
                    ExecutionError(
                        node="load_brand_brain",
                        severity=ErrorSeverity.WARNING,
                        code="BRAND_UNAVAILABLE",
                        message="This campaign's brand could not be loaded.",
                    )
                ]
            }

        brand = row_to_profile(brand_row)
        assets = await BrandAssetRepository(deps.session, deps.organization_id).list_for_brand(
            brand_row.id
        )
        from app.domain.brand import BrandAsset

        brand_assets = [
            BrandAsset(
                id=str(a.id),
                kind=a.kind,
                storage_key=a.storage_key,
                mime_type=a.mime_type,
                width=a.width,
                height=a.height,
            )
            for a in assets
        ]

        # Retrieve against whatever the campaign is already about, so the
        # knowledge slice is relevant to this conversation rather than generic.
        query = (
            " ".join(
                str(v)
                for v in (
                    state.campaign_inputs.campaign_objective,
                    state.campaign_inputs.product,
                    state.campaign_inputs.target_audience,
                )
                if v
            )
            or f"{brand.name} positioning audience tone claims"
        )

        knowledge: BrandKnowledge | None = None
        errors: list[ExecutionError] = []
        try:
            retriever = BrandKnowledgeRetriever(
                deps.session, deps.organization_id, embeddings=deps.embeddings
            )
            knowledge = await retriever.as_brand_knowledge(
                brand_id=brand_row.id, query=query, top_k=6
            )
        except ProviderError as exc:
            log.warning("brand_knowledge_unavailable", detail=exc.detail)
            errors.append(
                ExecutionError(
                    node="load_brand_brain",
                    severity=ErrorSeverity.WARNING,
                    code="BRAND_KNOWLEDGE_UNAVAILABLE",
                    message="Brand knowledge search is unavailable; continuing without it.",
                    detail=exc.detail,
                )
            )

        return {
            "brand": brand,
            "brand_assets": brand_assets,
            "brand_knowledge": knowledge,
            "errors": errors,
        }

    return node


def campaign_interviewer(deps: NodeDeps) -> Node:
    """Ask the best next question, then pause for the answer.

    On resume this node re-executes from the top and `interrupt()` returns the
    reply instead of pausing again — so everything before the interrupt must be
    safe to repeat.
    """

    async def node(state: CampaignState) -> dict[str, Any]:
        interviewer = CampaignInterviewer(deps.llm)
        inputs = state.campaign_inputs

        plan = await interviewer.plan(
            inputs=inputs,
            brand=state.brand,
            knowledge=state.brand_knowledge,
            conversation=list(state.conversation),
        )

        if plan.complete or state.interview_turn_count >= deps.max_interview_turns:
            # Out of budget is not the same as finished; say which it was, so
            # the specification can record the assumptions it proceeded on.
            return {
                "interview_complete": True,
                "pending_questions": [],
                "status": CampaignStatus.INTERVIEWING,
            }

        question = plan.question
        assert question is not None  # plan.complete is False, so there is one

        # Pause. The payload is exactly what the UI needs to render the turn.
        answer = interrupt(
            {
                "kind": "interview_question",
                "question": question.model_dump(mode="json"),
                "missing": plan.missing,
                "turn": state.interview_turn_count + 1,
            }
        )

        reply = (answer or {}).get("answer", "") if isinstance(answer, dict) else str(answer)
        turns = [
            ConversationTurn(
                role="assistant", content=question.question, targets_field=question.field
            ),
            ConversationTurn(role="user", content=reply, targets_field=question.field),
        ]

        try:
            extraction = await interviewer.interpret(answer=reply, question=question, inputs=inputs)
            updated = apply_updates(inputs, extraction)
        except ProviderError:
            # Malformed or failed model output must not lose the user's words.
            # Keep the reply verbatim against the asked field, marked inferred
            # so nothing downstream mistakes it for a clean extraction.
            updated = _record_raw_answer(inputs, question.field, reply)

        return {
            "conversation": turns,
            "campaign_inputs": updated,
            "pending_questions": [],
            "interview_complete": is_sufficient(updated),
            "interview_turn_count": state.interview_turn_count + 1,
            "status": CampaignStatus.INTERVIEWING,
        }

    return node


def _record_raw_answer(inputs: CampaignInputs, field: str, reply: str) -> CampaignInputs:
    """Fallback when extraction fails: never discard what the user typed."""
    if field not in FIELDS_BY_NAME or not reply.strip():
        return inputs
    data = inputs.model_dump()
    spec = FIELDS_BY_NAME[field]
    data[field] = [reply.strip()] if spec.is_list and field != "channels" else reply.strip()
    if field == "channels":
        data[field] = inputs.channels
    assertions = dict(inputs.assertions)
    assertions[field] = FieldAssertion(
        field=field,
        availability=Availability.KNOWN,
        certainty=Certainty.INFERRED,
        source="your answer, recorded as-is",
    )
    data["assertions"] = assertions
    return CampaignInputs.model_validate(data)


def build_campaign_specification(deps: NodeDeps) -> Node:
    """Compile the CAMPAIGN SPECIFICATION from everything gathered.

    Human-edited fields on an existing specification are carried forward
    untouched — recompiling must never quietly undo an edit, the same promise
    the prompt compiler makes at Gate 2 (ARCHITECTURE_REVIEW C-3).
    """

    async def node(state: CampaignState) -> dict[str, Any]:
        inputs = state.campaign_inputs
        brand = state.brand
        previous = state.campaign_brief

        assertions = dict(inputs.assertions)
        for name, assertion in (previous.field_assertions if previous else {}).items():
            if assertion.edited_by_human:
                assertions[name] = assertion

        def preserved(field: str, fallback: object) -> Any:
            """A human edit on the previous version wins over recompilation."""
            assertion = assertions.get(field)
            if previous is not None and assertion is not None and assertion.edited_by_human:
                return getattr(previous, field)
            return fallback

        missing_required = inputs.missing_required()
        assumptions = [
            f"{FIELDS_BY_NAME[f].name.replace('_', ' ')} was not settled during discovery"
            for f in missing_required
            if f in FIELDS_BY_NAME
        ]

        brief = CampaignBrief(
            campaign_id=state.campaign_id,
            version=(previous.version + 1) if previous else 1,
            title=preserved("title", _title(inputs, brand)),
            objective=preserved("objective", inputs.campaign_objective or "Not yet defined"),
            audience=preserved(
                "audience",
                inputs.target_audience
                or (brand.audience_description if brand else None)
                or "Not yet defined",
            ),
            product=preserved("product", inputs.product or "Not yet defined"),
            key_message=preserved("key_message", inputs.key_message or "Not yet defined"),
            cta=preserved("cta", inputs.cta or "Learn more"),
            channels=preserved("channels", list(inputs.channels)),
            region=preserved("region", inputs.region),
            language=inputs.language,
            tone=preserved(
                "tone",
                list(inputs.campaign_tone)
                or list(inputs.tone)
                or (list(brand.voice.tone_attributes) if brand else []),
            ),
            desired_emotional_response=preserved(
                "desired_emotional_response", inputs.desired_emotional_response
            ),
            campaign_tone=preserved("campaign_tone", list(inputs.campaign_tone)),
            key_offer=preserved("key_offer", inputs.key_offer),
            timing_occasion=preserved("timing_occasion", inputs.timing_occasion),
            required_elements=preserved("required_elements", list(inputs.required_elements)),
            avoid_restrictions=preserved("avoid_restrictions", list(inputs.avoid_restrictions)),
            brand_requirements=list(brand.approved_claims[:5]) if brand else [],
            constraints=list(inputs.constraints),
            field_assertions=assertions,
            rationale=(
                "Built from your discovery conversation"
                + (" and your brand guidelines." if brand else ".")
            ),
            assumptions_made=assumptions,
        )

        return {
            "campaign_brief": brief,
            "status": CampaignStatus.AWAITING_APPROVAL,
        }

    return node


def _title(inputs: CampaignInputs, brand: object | None) -> str:
    parts = [getattr(brand, "name", None), inputs.product, inputs.campaign_objective]
    text = " — ".join(p for p in parts if p)
    return (text or "Untitled campaign")[:120]
