"""Node contracts.

"Each major node must have defined inputs and outputs" is easy to write in a
document and easy to violate in code. So the contract lives here as data, and
`tests/test_node_contracts.py` enforces it three ways:

  1. every declared field name is a real `CampaignState` field;
  2. every registered node has a contract (and vice versa);
  3. at runtime under test, a node that returns an undeclared key fails.

`FailureMode` is part of the contract because "what happens when this node
fails" is a design decision, not an implementation detail. A DEGRADE node must
never take the run down, and a FATAL node must never pretend it succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.graph.state import STATE_FIELDS


class FailureMode(StrEnum):
    FATAL = "fatal"  # route to terminal_failure; the run cannot continue
    DEGRADE = "degrade"  # record a warning, write a safe default, continue
    RETRY_THEN_FATAL = "retry_then_fatal"
    PER_ITEM = "per_item"  # partial success is success (generation)
    NONE = "none"  # human gates: they wait, they do not fail


@dataclass(frozen=True)
class NodeContract:
    name: str
    purpose: str
    reads: frozenset[str]
    writes: frozenset[str]
    interrupts: bool = False
    failure_mode: FailureMode = FailureMode.RETRY_THEN_FATAL
    calls_llm: bool = False
    calls_image: bool = False
    notes: str = ""

    def undeclared_writes(self, actual: frozenset[str] | set[str]) -> set[str]:
        """Keys a node returned but never declared. Must always be empty."""
        return set(actual) - set(self.writes)


def _c(
    name: str,
    purpose: str,
    reads: tuple[str, ...],
    writes: tuple[str, ...],
    **kw: object,
) -> NodeContract:
    return NodeContract(
        name=name,
        purpose=purpose,
        reads=frozenset(reads),
        writes=frozenset(writes),
        **kw,  # type: ignore[arg-type]
    )


#: Mirrors the table in docs/GRAPH_SPEC.md §2. Keep them in step; the doc
#: explains, this enforces.
NODE_CONTRACTS: dict[str, NodeContract] = {
    c.name: c
    for c in (
        _c(
            "load_project",
            "Resolve tenancy scope. Nothing may run without it.",
            reads=("project_id", "user_id"),
            writes=("project", "organization", "user", "status"),
            failure_mode=FailureMode.FATAL,
        ),
        _c(
            "load_brand_brain",
            "Load the brand profile, assets and retrieved brand knowledge.",
            # `campaign_id` resolves the campaign row, and the brand hangs off
            # that row — never off a request parameter (M1_SECURITY_AUDIT A-5).
            reads=("campaign_id", "project", "campaign_inputs"),
            writes=("brand", "brand_assets", "brand_knowledge", "errors"),
            failure_mode=FailureMode.DEGRADE,
            notes="Degrades to profile-only so a failed ingest cannot block a campaign.",
        ),
        _c(
            "campaign_interviewer",
            "Turn vague intent into structured, sufficient campaign inputs.",
            reads=("conversation", "brand", "campaign_inputs", "interview_turn_count"),
            writes=(
                "conversation",
                "campaign_inputs",
                "pending_questions",
                "interview_complete",
                "interview_turn_count",
                "status",
            ),
            interrupts=True,
            calls_llm=True,
            failure_mode=FailureMode.RETRY_THEN_FATAL,
            notes="Asks only gap-filling questions; stops as soon as inputs are sufficient.",
        ),
        _c(
            "reference_intelligence",
            "Learn style (not layout) from uploaded references.",
            reads=("references", "brand"),
            writes=("reference_analysis", "aggregate_style", "creative_preferences", "errors"),
            calls_llm=True,
            failure_mode=FailureMode.DEGRADE,
        ),
        _c(
            "market_intelligence",
            "Resolve regional, cultural and market context.",
            reads=("campaign_inputs", "brand"),
            writes=("market_context", "regional_context", "errors"),
            calls_llm=True,
            failure_mode=FailureMode.DEGRADE,
        ),
        _c(
            "campaign_brief_builder",
            "Synthesise inputs + brand + references + market into one brief.",
            reads=(
                "campaign_inputs",
                "brand",
                "brand_knowledge",
                "aggregate_style",
                "market_context",
                "regional_context",
            ),
            writes=("campaign_brief", "status"),
            calls_llm=True,
        ),
        _c(
            "load_creative_context",
            "Assemble brand, specification, reference style and preferences.",
            reads=("campaign_id",),
            writes=("creative_context", "errors", "status"),
            failure_mode=FailureMode.DEGRADE,
            notes="Reuses the Milestone 4 CreativeContextService; builds nothing itself.",
        ),
        _c(
            "creative_director",
            "Produce three distinct strategic directions and a recommendation.",
            reads=("creative_context", "creative_revision", "user_feedback"),
            writes=("direction_set", "status"),
            calls_llm=True,
            notes=(
                "Consumes the assembled CreativeContext rather than re-deriving brand "
                "rules and preferences. Distinctness is checked deterministically; a "
                "near-duplicate set triggers one regeneration with instructions to diverge."
            ),
        ),
        _c(
            "human_strategy_approval",
            "GATE 1 — the human picks a direction.",
            reads=("direction_set",),
            writes=(
                "approval_states",
                "selected_direction",
                "user_feedback",
                "creative_revision",
                "pending_gate",
                "status",
            ),
            interrupts=True,
            failure_mode=FailureMode.NONE,
        ),
        _c(
            "creative_specification_builder",
            "Turn the approved direction into a detailed execution plan.",
            reads=("creative_context", "selected_direction", "creative_specification"),
            writes=("creative_specification", "status"),
            calls_llm=True,
            notes=(
                "Owns `creative_specification`. A field a human edited is carried "
                "forward untouched — regenerating must never undo an edit."
            ),
        ),
        _c(
            "prompt_compiler",
            "Compile the approved direction into a spec, then per-provider prompts.",
            reads=(
                "selected_direction",
                "campaign_brief",
                "brand",
                "revision_delta",
                "creative_specification",
                "approval_states",
                "guardian_precheck",
            ),
            # No longer writes `creative_specification`:
            # `creative_specification_builder` owns it, and the compiler only
            # renders prompts from it (Milestone 6).
            writes=("canonical_prompt", "model_prompts", "status"),
            # Milestone 6 made compilation deterministic: the approved
            # specification is already structured, so rearranging it into image
            # controls is a pure function. A model here would spend credit to
            # make the result unrepeatable.
            calls_llm=False,
            notes=(
                "Adapters format; they never change meaning (ADR-005). Recompiling is "
                "not regenerating from scratch: a field a human edited at Gate 2 "
                "(ModelPrompt.edited_by_user, or an edit recorded in approval_states) "
                "is carried forward untouched. Also reads guardian_precheck so a "
                "failed pre-check is repaired here rather than by the detector. "
                "Milestone 6 runs this as a service (PromptCompiler), not a registered "
                "node — see ADR-012."
            ),
        ),
        _c(
            "brand_guardian_precheck",
            "Catch brand violations before spending generation credit.",
            reads=("creative_specification", "model_prompts", "brand"),
            writes=("guardian_precheck", "precheck_attempts", "errors"),
            calls_llm=True,
            failure_mode=FailureMode.DEGRADE,
            notes=(
                "Reports only. Repair belongs to prompt_compiler, which the routing "
                "table already returns to on a failed pre-check — a detector that "
                "also rewrites its subject owns two jobs (ARCHITECTURE_REVIEW C-4)."
            ),
        ),
        _c(
            "human_specification_approval",
            "GATE 2 — the human approves or edits the Creative Specification.",
            reads=("creative_specification", "model_prompts", "guardian_precheck"),
            # Records the decision only. An edit is applied by the service
            # and pushed into graph state, exactly as the Campaign
            # Specification edit path works — so the builder stays the single
            # owner of `creative_specification`.
            writes=("approval_states", "user_feedback", "pending_gate", "status"),
            interrupts=True,
            failure_mode=FailureMode.NONE,
        ),
        _c(
            "generation_router",
            "Choose providers and create idempotent jobs.",
            reads=("model_prompts", "generation_jobs", "providers_attempted"),
            writes=("generation_jobs", "providers_attempted", "status"),
            failure_mode=FailureMode.FATAL,
            notes="Fatal only when no provider at all is configured — mock always is.",
        ),
        _c(
            "image_generation",
            "Execute jobs. Partial success is success.",
            reads=("generation_jobs",),
            writes=("generation_jobs", "generated_assets", "errors"),
            calls_image=True,
            failure_mode=FailureMode.PER_ITEM,
        ),
        _c(
            "creative_evaluator",
            "Score each asset: is this a good creative?",
            reads=("generated_assets", "campaign_brief", "creative_specification", "brand"),
            writes=("evaluation_results", "errors", "status"),
            calls_llm=True,
            failure_mode=FailureMode.DEGRADE,
        ),
        _c(
            "brand_guardian",
            "Judge each asset: is this acceptable for THIS brand?",
            reads=("generated_assets", "brand", "creative_specification", "regional_context"),
            writes=("brand_guardian_results", "errors"),
            calls_llm=True,
            failure_mode=FailureMode.DEGRADE,
            notes="A failed check yields UNKNOWN, never an implicit PASS.",
        ),
        _c(
            "creative_ranking",
            "Rank assets; a guardian failure outweighs a high score.",
            reads=("evaluation_results", "brand_guardian_results", "generated_assets"),
            writes=("ranked_assets", "asset_recommendation", "errors"),
            failure_mode=FailureMode.DEGRADE,
            notes="On failure falls back to generation order, and says so.",
        ),
        _c(
            "human_final_selection",
            "GATE 3 — the human selects, regenerates or requests changes.",
            reads=("ranked_assets", "evaluation_results", "brand_guardian_results"),
            writes=("approval_states", "selected_asset", "user_feedback", "pending_gate", "status"),
            interrupts=True,
            failure_mode=FailureMode.NONE,
        ),
        _c(
            "revision_planner",
            "Interpret feedback as an explicit KEEP/CHANGE delta.",
            reads=("user_feedback", "creative_specification", "selected_asset"),
            writes=("revision_delta", "revision_history", "iteration_count", "status"),
            calls_llm=True,
            notes="Never guesses: unclear feedback goes back to the human.",
        ),
        _c(
            "final_asset_builder",
            "Compose brand elements deterministically over the chosen plate.",
            reads=("selected_asset", "creative_specification", "brand", "brand_assets"),
            writes=("final_design", "final_assets", "status"),
            notes="Pure render (ADR-006). No model call, so it should never fail.",
        ),
        _c(
            "export",
            "Re-lay the approved design into every requested channel.",
            reads=("final_design", "campaign_brief", "brand_assets"),
            writes=("final_assets", "export_manifest", "status"),
            failure_mode=FailureMode.PER_ITEM,
        ),
        _c(
            "terminal_failure",
            "Write a terminal status. A run never ends undefined.",
            reads=("errors",),
            writes=("status",),
            failure_mode=FailureMode.NONE,
        ),
    )
}

#: Nodes that pause for a human. The API's resume path is built from this.
INTERRUPTING_NODES: frozenset[str] = frozenset(
    name for name, c in NODE_CONTRACTS.items() if c.interrupts
)


def unknown_fields() -> dict[str, set[str]]:
    """Any declared field that is not a real `CampaignState` field.

    Always empty; a test asserts it. This is what stops the contract drifting
    away from the state it is supposed to describe.
    """
    bad: dict[str, set[str]] = {}
    for name, c in NODE_CONTRACTS.items():
        offenders = (set(c.reads) | set(c.writes)) - set(STATE_FIELDS)
        if offenders:
            bad[name] = offenders
    return bad


def writers_of(field_name: str) -> list[str]:
    """Which nodes may write a field. Used to review ownership."""
    return sorted(n for n, c in NODE_CONTRACTS.items() if field_name in c.writes)


__all__ = [
    "INTERRUPTING_NODES",
    "NODE_CONTRACTS",
    "FailureMode",
    "NodeContract",
    "unknown_fields",
    "writers_of",
]
