"""Node contract integrity.

`docs/GRAPH_SPEC.md` describes the contracts; this file enforces them. The
runtime check (a node writing an undeclared key) activates automatically once
`app/graph/nodes/` exists in Milestone 4 — until then the structural checks run
and the runtime one is explicitly skipped rather than quietly passing.
"""

from __future__ import annotations

import importlib.util

import pytest

from app.domain.approval import Gate
from app.graph.contracts import (
    INTERRUPTING_NODES,
    NODE_CONTRACTS,
    FailureMode,
    NodeContract,
    unknown_fields,
    writers_of,
)
from app.graph.state import STATE_FIELDS

pytestmark = pytest.mark.unit

#: The three gates promised by the product, mapped to their nodes.
EXPECTED_GATE_NODES = {
    Gate.STRATEGY: "human_strategy_approval",
    Gate.SPECIFICATION: "human_specification_approval",
    Gate.FINAL: "human_final_selection",
}


class TestContractIntegrity:
    def test_every_declared_field_exists_on_the_state(self) -> None:
        """Stops the contract drifting away from the state it describes."""
        assert unknown_fields() == {}

    @pytest.mark.parametrize("contract", NODE_CONTRACTS.values(), ids=lambda c: c.name)
    def test_each_node_declares_reads_writes_and_a_purpose(self, contract: NodeContract) -> None:
        assert contract.purpose.strip(), f"{contract.name} has no stated purpose"
        assert contract.writes, f"{contract.name} writes nothing — why does it exist?"
        assert set(contract.writes) <= set(STATE_FIELDS)
        assert set(contract.reads) <= set(STATE_FIELDS)

    def test_contract_keys_match_their_node_names(self) -> None:
        for key, contract in NODE_CONTRACTS.items():
            assert key == contract.name


class TestGates:
    def test_all_three_product_gates_exist_and_interrupt(self) -> None:
        for gate, node in EXPECTED_GATE_NODES.items():
            assert node in NODE_CONTRACTS, f"missing node for gate {gate}"
            assert NODE_CONTRACTS[node].interrupts, f"{node} must pause for a human"

    def test_interrupting_nodes_are_exactly_the_human_gates_and_the_interviewer(self) -> None:
        expected = set(EXPECTED_GATE_NODES.values()) | {"campaign_interviewer"}
        assert set(INTERRUPTING_NODES) == expected

    def test_gate_nodes_never_fail_they_wait(self) -> None:
        for node in EXPECTED_GATE_NODES.values():
            assert NODE_CONTRACTS[node].failure_mode is FailureMode.NONE

    def test_every_gate_records_its_decision(self) -> None:
        """Without this the audit trail has holes and resume is ambiguous."""
        for node in EXPECTED_GATE_NODES.values():
            assert "approval_states" in NODE_CONTRACTS[node].writes


class TestOwnership:
    @pytest.mark.parametrize(
        "field_name",
        ["campaign_brief", "creative_specification", "final_design", "revision_delta"],
    )
    def test_single_writer_for_critical_artefacts(self, field_name: str) -> None:
        """Two nodes writing the brief means nobody owns it."""
        assert len(writers_of(field_name)) == 1, (
            f"{field_name} is written by {writers_of(field_name)}"
        )

    def test_errors_are_only_written_by_nodes_that_can_degrade(self) -> None:
        for name, contract in NODE_CONTRACTS.items():
            if "errors" in contract.writes:
                assert contract.failure_mode in (
                    FailureMode.DEGRADE,
                    FailureMode.PER_ITEM,
                ), f"{name} records errors but is not a degrading node"

    @pytest.mark.parametrize(
        ("counter", "owner"),
        [("interview_turn_count", "campaign_interviewer"), ("iteration_count", "revision_planner")],
    )
    def test_each_loop_budget_has_exactly_one_owner(self, counter: str, owner: str) -> None:
        """C-2 regression guard. Both loops once shared `iteration_count`, so an
        eight-turn interview silently spent the whole revision budget."""
        assert writers_of(counter) == [owner]

    def test_the_detector_does_not_rewrite_what_it_inspects(self) -> None:
        """C-4 regression guard: `brand_guardian_precheck` reports, and
        `prompt_compiler` repairs — the routing table already sends failures
        back to the compiler."""
        precheck = NODE_CONTRACTS["brand_guardian_precheck"]
        assert "model_prompts" in precheck.reads
        assert "model_prompts" not in precheck.writes
        assert "guardian_precheck" in NODE_CONTRACTS["prompt_compiler"].reads

    def test_the_compiler_can_see_user_edits_it_must_preserve(self) -> None:
        """C-3 regression guard: Gate 2 accepts edits and routes back to the
        compiler. A compiler that cannot read them overwrites them."""
        compiler = NODE_CONTRACTS["prompt_compiler"]
        assert {"creative_specification", "approval_states"} <= set(compiler.reads)

    def test_scope_fields_are_never_rewritten(self) -> None:
        """campaign_id / project_id / user_id are set at START and are fixed;
        a node rewriting them would move a run into another tenant."""
        for immutable in ("campaign_id", "project_id", "user_id"):
            assert writers_of(immutable) == []


class TestFailureModes:
    def test_degrading_nodes_can_record_what_went_wrong(self) -> None:
        for name, contract in NODE_CONTRACTS.items():
            if contract.failure_mode is FailureMode.DEGRADE:
                assert "errors" in contract.writes, f"{name} degrades silently"

    def test_generation_tolerates_partial_failure(self) -> None:
        assert NODE_CONTRACTS["image_generation"].failure_mode is FailureMode.PER_ITEM

    def test_there_is_a_terminal_node(self) -> None:
        assert "terminal_failure" in NODE_CONTRACTS
        assert "status" in NODE_CONTRACTS["terminal_failure"].writes


class TestProviderUsageIsDeclared:
    def test_only_generation_calls_an_image_provider(self) -> None:
        image_callers = {n for n, c in NODE_CONTRACTS.items() if c.calls_image}
        assert image_callers == {"image_generation"}

    def test_deterministic_nodes_call_no_model(self) -> None:
        """The final composition must be reproducible (ADR-006), and ranking
        must be arithmetic, not opinion."""
        for name in ("final_asset_builder", "export", "creative_ranking", "generation_router"):
            contract = NODE_CONTRACTS[name]
            assert not contract.calls_llm and not contract.calls_image, f"{name} must be pure"


@pytest.mark.skipif(
    importlib.util.find_spec("app.graph.nodes") is None,
    reason="nodes land in Milestone 4; the runtime write-check activates then",
)
class TestRuntimeWrites:
    def test_every_registered_node_has_a_contract(self) -> None:
        """A subset, not equality: nodes arrive per milestone, and a contract
        without a node is a plan rather than a defect. The direction that
        matters is that nothing runs without a declared contract."""
        from app.graph.nodes import NODE_REGISTRY  # type: ignore[attr-defined]

        assert set(NODE_REGISTRY) <= set(NODE_CONTRACTS), (
            f"nodes with no contract: {set(NODE_REGISTRY) - set(NODE_CONTRACTS)}"
        )

    def test_the_milestone_3_discovery_nodes_are_built(self) -> None:
        from app.graph.nodes import NODE_REGISTRY  # type: ignore[attr-defined]

        assert {
            "load_project",
            "load_brand_brain",
            "campaign_interviewer",
            "campaign_brief_builder",
        } <= set(NODE_REGISTRY)
