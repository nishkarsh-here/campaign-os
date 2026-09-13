"""Graph assembly.

Kept in one small module so the LangGraph API touches exactly one file
(ROADMAP risk: "LangGraph API churn"). Nodes stay plain async functions and are
testable without importing LangGraph at all.

The Milestone 3 graph is the discovery half:

    START -> load_project -> load_brand_brain -> campaign_interviewer
                                                      |  ^ (loop: more to ask)
                                                      v
                                             campaign_brief_builder -> END

The interviewer is the interrupt point. Everything after it — creative
directions, prompts, generation — belongs to later milestones and is not wired.
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import NODE_REGISTRY
from app.graph.nodes.deps import NodeDeps
from app.graph.state import CampaignState

INTERVIEW = "campaign_interviewer"
BUILD_SPEC = "campaign_brief_builder"

# --- Milestone 5 -----------------------------------------------------------
LOAD_CONTEXT = "load_creative_context"
DIRECTOR = "creative_director"
STRATEGY_GATE = "human_strategy_approval"
BUILD_CREATIVE_SPEC = "creative_specification_builder"
SPEC_GATE = "human_specification_approval"


def route_after_interview(state: CampaignState) -> str:
    """Loop until the interview is complete, then compile.

    Guarded by `interview_turn_count`, a budget separate from the revision
    budget so a long conversation cannot exhaust the ability to revise later
    (ARCHITECTURE_REVIEW C-2).
    """
    return BUILD_SPEC if state.interview_complete else INTERVIEW


def build_discovery_graph(deps: NodeDeps, *, checkpointer: Any | None = None) -> Any:
    """Compile the discovery graph.

    `checkpointer` is required for interrupt/resume to survive a process
    restart; it is optional here only so unit tests can compile the graph
    without a database.
    """
    builder = StateGraph(CampaignState)
    for name in ("load_project", "load_brand_brain", INTERVIEW, BUILD_SPEC):
        # `add_node`'s overloads do not admit a precisely-typed async callable
        # alias. The nodes keep their real signatures; the cast is confined to
        # this one library boundary rather than weakening them.
        builder.add_node(name, cast(Any, NODE_REGISTRY[name](deps)))

    builder.add_edge(START, "load_project")
    builder.add_edge("load_project", "load_brand_brain")
    builder.add_edge("load_brand_brain", INTERVIEW)
    builder.add_conditional_edges(
        INTERVIEW, route_after_interview, {INTERVIEW: INTERVIEW, BUILD_SPEC: BUILD_SPEC}
    )
    builder.add_edge(BUILD_SPEC, END)

    return builder.compile(checkpointer=checkpointer)


def route_after_strategy_gate(state: CampaignState) -> str:
    """Approve moves on; reject and revise regenerate.

    Guarded by the direction-set version rather than an unbounded loop: a
    human who keeps rejecting eventually gets the set they have, not an
    infinite spend.
    """
    if state.selected_direction is not None:
        return BUILD_CREATIVE_SPEC
    version = state.direction_set.version if state.direction_set else 1
    return DIRECTOR if version < MAX_DIRECTION_VERSIONS else BUILD_CREATIVE_SPEC


def route_after_specification_gate(state: CampaignState) -> str:
    """Approval ends Milestone 5. Anything else rebuilds the plan.

    Milestone 5 stops at the approved Creative Specification — no image is
    generated here. Milestone 6 picks it up from the database.
    """
    from app.domain.approval import Decision, Gate

    decision = state.approval_states.get(Gate.SPECIFICATION.value)
    if decision is not None and decision.decision is Decision.APPROVE:
        return END
    return BUILD_CREATIVE_SPEC


#: A rejected set regenerates, but not forever.
MAX_DIRECTION_VERSIONS = 4


def build_creative_graph(deps: NodeDeps, *, checkpointer: Any | None = None) -> Any:
    """The Milestone 5 creative stage.

    A separate graph from discovery, on a derived thread
    (`<campaign_id>:creative`). Discovery ends at a confirmed Campaign
    Specification and the creative stage begins from that *persisted* artefact
    — so the two stages are independently resumable and Milestone 3 keeps
    working exactly as it did. Both use the same `CampaignState` and the same
    checkpoint infrastructure; only the thread differs.
    """
    builder = StateGraph(CampaignState)
    for name in (LOAD_CONTEXT, DIRECTOR, STRATEGY_GATE, BUILD_CREATIVE_SPEC, SPEC_GATE):
        builder.add_node(name, cast(Any, NODE_REGISTRY[name](deps)))

    builder.add_edge(START, LOAD_CONTEXT)
    builder.add_edge(LOAD_CONTEXT, DIRECTOR)
    builder.add_edge(DIRECTOR, STRATEGY_GATE)
    builder.add_conditional_edges(
        STRATEGY_GATE,
        route_after_strategy_gate,
        {DIRECTOR: DIRECTOR, BUILD_CREATIVE_SPEC: BUILD_CREATIVE_SPEC},
    )
    builder.add_edge(BUILD_CREATIVE_SPEC, SPEC_GATE)
    builder.add_conditional_edges(
        SPEC_GATE,
        route_after_specification_gate,
        {BUILD_CREATIVE_SPEC: BUILD_CREATIVE_SPEC, END: END},
    )
    return builder.compile(checkpointer=checkpointer)


def creative_thread_id(campaign_id: str) -> str:
    """The creative stage's thread. Derived from a scope-checked campaign row,
    never from a request parameter (M1_SECURITY_AUDIT A-5)."""
    return f"{campaign_id}:creative"
