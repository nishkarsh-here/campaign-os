"""Graph nodes.

Milestone 3 builds the discovery half of the graph. The rest of
`NODE_CONTRACTS` stays declared-but-unbuilt until its milestone — a contract
without a node is a plan, and `tests/test_node_contracts.py` checks that every
node that *does* exist has one.

Every node is a plain `async def (state) -> dict` closed over a `NodeDeps`
bundle. That keeps them testable without LangGraph, and keeps providers
injected rather than imported (CLAUDE.md rule 2).
"""

from app.graph.nodes.creative import (
    creative_director,
    creative_specification_builder,
    human_specification_approval,
    human_strategy_approval,
    load_creative_context,
)
from app.graph.nodes.deps import NodeDeps
from app.graph.nodes.discovery import (
    build_campaign_specification,
    campaign_interviewer,
    load_brand_brain,
    load_project,
)

#: Node name -> factory. The name must match a `NodeContract`.
NODE_REGISTRY = {
    "load_project": load_project,
    "load_brand_brain": load_brand_brain,
    "campaign_interviewer": campaign_interviewer,
    "campaign_brief_builder": build_campaign_specification,
    # Milestone 5
    "load_creative_context": load_creative_context,
    "creative_director": creative_director,
    "human_strategy_approval": human_strategy_approval,
    "creative_specification_builder": creative_specification_builder,
    "human_specification_approval": human_specification_approval,
}

__all__ = ["NODE_REGISTRY", "NodeDeps"]
