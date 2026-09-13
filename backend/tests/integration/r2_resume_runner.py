"""R-2 spike runner — executed as a *separate OS process* by the test.

Phase A starts a graph and runs it into an `interrupt()`, then the process
exits. Phase B is a brand-new process with a brand-new saver, graph object and
Python interpreter: it must resume from nothing but the Postgres checkpoint.

Run directly:
    python -m tests.integration.r2_resume_runner a <thread_id> <dsn>
    python -m tests.integration.r2_resume_runner b <thread_id> <dsn>

Each phase prints one JSON object on stdout. The test asserts on it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.domain.approval import ApprovalDecision, Decision, Gate, PendingGate
from app.domain.brand import BrandColor, BrandProfile
from app.domain.campaign import CampaignBrief, ConversationTurn
from app.domain.common import CampaignStatus, Channel, ExecutionError, JobStatus, StyleFamily
from app.domain.generation import GenerationJob
from app.graph.serde import checkpointer_kwargs
from app.graph.state import CampaignState

THREAD_CONFIG_KEY = "configurable"


# --------------------------------------------------------------------------
# A miniature three-node graph. Deliberately NOT the real graph: this spike
# tests the persistence mechanism, not the product's nodes.
# --------------------------------------------------------------------------
def _populate(state: CampaignState) -> dict[str, Any]:
    """Write a realistically deep slice of state: nested models, enums,
    datetimes, and both reducer kinds."""
    return {
        "brand": BrandProfile(
            id="brand-1",
            organization_id="org-1",
            name="Northline Materials",
            positioning="Engineered building materials.",
            colors=[
                BrandColor(name="Graphite", hex="#1F2933", role="primary"),
                BrandColor(name="Signal", hex="#E4572E", role="accent"),
            ],
            preferred_styles=[StyleFamily.PREMIUM, StyleFamily.TECHNICAL],
            prohibited_claims=["indestructible"],
        ),
        "campaign_brief": CampaignBrief(
            campaign_id=state.campaign_id,
            title="Premium launch",
            objective="Establish the façade system as the premium specification.",
            audience="Architects in Maharashtra",
            product="Northline FS-9",
            key_message="Engineered to outlast the building it clads.",
            cta="Request a specification pack",
            channels=[Channel.INSTAGRAM_POST, Channel.LINKEDIN],
            region="Maharashtra, India",
        ),
        "conversation": [ConversationTurn(role="user", content="premium campaign please")],
        "generation_jobs": [
            GenerationJob(
                id="job-1",
                campaign_id=state.campaign_id,
                prompt_id="p-1",
                specification_id="s-1",
                batch_id="b-1",
                provider="mock",
                model="mock-1",
                status=JobStatus.PENDING,
                idempotency_key="key-job-1",
            )
        ],
        "errors": [
            ExecutionError(node="populate", code="DEMO_WARNING", message="a recorded warning")
        ],
        "status": CampaignStatus.STRATEGY,
    }


def _gate(state: CampaignState) -> dict[str, Any]:
    """The human gate. On resume this node re-executes from the top and
    `interrupt()` returns the resume value instead of pausing again."""
    answer = interrupt(
        PendingGate(
            gate=Gate.STRATEGY,
            options=[Decision.APPROVE, Decision.REJECT],
            prompt_text="Approve the strategy?",
            payload={"brand": state.brand.name if state.brand else None},
        ).model_dump(mode="json")
    )
    decision = ApprovalDecision(gate=Gate.STRATEGY, decision=Decision(answer["decision"]))
    return {
        "approval_states": {Gate.STRATEGY.value: decision},
        "pending_gate": None,
        # Reducer checks: append must not replace, upsert must not duplicate.
        "conversation": [ConversationTurn(role="assistant", content="strategy approved")],
        "generation_jobs": [
            GenerationJob(
                id="job-1",
                campaign_id=state.campaign_id,
                prompt_id="p-1",
                specification_id="s-1",
                batch_id="b-1",
                provider="mock",
                model="mock-1",
                status=JobStatus.COMPLETED,
                idempotency_key="key-job-1",
            )
        ],
    }


def _finish(state: CampaignState) -> dict[str, Any]:
    return {"status": CampaignStatus.COMPLETED}


def build_graph() -> Any:
    builder = StateGraph(CampaignState)
    builder.add_node("populate", _populate)
    builder.add_node("gate", _gate)
    builder.add_node("finish", _finish)
    builder.add_edge(START, "populate")
    builder.add_edge("populate", "gate")
    builder.add_edge("gate", "finish")
    builder.add_edge("finish", END)
    return builder


def _describe(state: Any) -> dict[str, Any]:
    """Report the facts the test asserts on — including the *runtime types*,
    which is the crux: a node calling `state.brand.primary_color()` breaks if
    the checkpoint round-trips a plain dict."""

    # `ainvoke` returns a dict while `aget_state().values` returns the model,
    # so read either shape rather than caring which call produced it.
    def field(name: str) -> Any:
        return getattr(state, name) if hasattr(state, name) else state.get(name)

    brand = field("brand")
    brief = field("campaign_brief")
    convo = field("conversation")
    jobs = field("generation_jobs")
    errors = field("errors")
    approvals = field("approval_states")
    status = field("status")

    return {
        "brand_type": type(brand).__name__,
        "brand_name": getattr(brand, "name", None),
        "brand_primary_hex": (
            brand.primary_color().hex if hasattr(brand, "primary_color") and brand else None
        ),
        "brand_styles": [str(s) for s in getattr(brand, "preferred_styles", [])],
        "brief_type": type(brief).__name__,
        "brief_channels": [str(c) for c in getattr(brief, "channels", [])],
        "conversation_len": len(convo or []),
        "conversation_roles": [t.role for t in (convo or [])],
        "job_count": len(jobs or []),
        "job_statuses": [str(j.status) for j in (jobs or [])],
        "job_type": type(jobs[0]).__name__ if jobs else None,
        "error_count": len(errors or []),
        "error_has_datetime": bool(errors) and hasattr(errors[0].occurred_at, "year"),
        "approval_gates": sorted(approvals or {}),
        "approval_decision": (
            str(approvals[Gate.STRATEGY.value].decision)
            if approvals and Gate.STRATEGY.value in approvals
            else None
        ),
        "status": str(status),
    }


async def run(phase: str, thread_id: str, dsn: str) -> dict[str, Any]:
    async with AsyncPostgresSaver.from_conn_string(dsn, **checkpointer_kwargs()) as saver:
        if phase == "a":
            await saver.setup()
        graph = build_graph().compile(checkpointer=saver)
        config = {THREAD_CONFIG_KEY: {"thread_id": thread_id}}

        if phase == "a":
            result = await graph.ainvoke(
                CampaignState(campaign_id="camp-r2", project_id="proj-1", user_id="user-1"),
                config,
            )
            snapshot = await graph.aget_state(config)
            return {
                "phase": "a",
                "interrupted": bool(result.get("__interrupt__")),
                "next_nodes": list(snapshot.next),
                "state": _describe(snapshot.values),
            }

        # Phase B: a brand-new process. Nothing but the checkpoint carries over.
        before = await graph.aget_state(config)
        result = await graph.ainvoke(Command(resume={"decision": "APPROVE"}), config)
        after = await graph.aget_state(config)
        return {
            "phase": "b",
            "resumed_from_pending_node": list(before.next),
            "state_before_resume": _describe(before.values),
            "completed": not after.next,
            "state": _describe(result),
        }


def main() -> int:
    phase, thread_id, dsn = sys.argv[1], sys.argv[2], sys.argv[3]
    print(json.dumps(asyncio.run(run(phase, thread_id, dsn))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
