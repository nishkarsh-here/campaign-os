"""CampaignState and its reducers.

The reducers decide whether concurrent nodes cooperate or destroy each other's
work, so they are tested directly rather than only through the graph.
"""

from __future__ import annotations

import json
from typing import get_args

import pytest
from pydantic import ValidationError

from app.domain import ExecutionError, GenerationJob, JobStatus
from app.domain.approval import ApprovalDecision, Decision, Gate
from app.domain.campaign import ConversationTurn
from app.domain.reference import ReferenceAnalysis
from app.graph.reducers import append, merge_dict, upsert_by_id, upsert_on
from app.graph.state import STATE_FIELDS, CampaignState, initial_state

pytestmark = pytest.mark.unit


def _job(job_id: str, status: JobStatus = JobStatus.PENDING) -> GenerationJob:
    return GenerationJob(
        id=job_id,
        campaign_id="camp-1",
        prompt_id="p-1",
        specification_id="s-1",
        batch_id="b-1",
        provider="mock",
        model="mock-1",
        status=status,
        idempotency_key=f"key-{job_id}",
        error=(
            ExecutionError(node="image_generation", code="X", message="failed")
            if status is JobStatus.FAILED
            else None
        ),
    )


class TestAppendReducer:
    def test_appends_rather_than_replaces(self) -> None:
        turns = [ConversationTurn(role="user", content="one")]
        merged = append(turns, [ConversationTurn(role="assistant", content="two")])
        assert [t.content for t in merged] == ["one", "two"]

    def test_accepts_a_bare_item(self) -> None:
        assert len(append([], ConversationTurn(role="user", content="x"))) == 1

    def test_none_update_leaves_the_list_untouched(self) -> None:
        turns = [ConversationTurn(role="user", content="one")]
        assert append(turns, None) == turns

    def test_does_not_mutate_the_input(self) -> None:
        """Reducers must be pure — LangGraph may hold the previous value."""
        original = [ConversationTurn(role="user", content="one")]
        append(original, ConversationTurn(role="user", content="two"))
        assert len(original) == 1


class TestUpsertReducer:
    def test_new_ids_are_appended(self) -> None:
        merged = upsert_by_id([_job("a")], [_job("b")])
        assert [j.id for j in merged] == ["a", "b"]

    def test_existing_id_is_replaced_in_place(self) -> None:
        """A job moving PENDING -> COMPLETED must stay one row. With a plain
        append reducer this is the bug that shows two of every image."""
        merged = upsert_by_id([_job("a"), _job("b")], [_job("a", JobStatus.COMPLETED)])
        assert len(merged) == 2
        assert [j.id for j in merged] == ["a", "b"]
        assert merged[0].status is JobStatus.COMPLETED

    def test_ordering_is_stable_across_updates(self) -> None:
        merged = upsert_by_id(
            [_job("a"), _job("b"), _job("c")],
            [_job("c", JobStatus.RUNNING), _job("a", JobStatus.RUNNING)],
        )
        assert [j.id for j in merged] == ["a", "b", "c"]


class TestUpsertKeysMatchTheirItemTypes:
    """C-1 regression guard.

    `reference_analysis` was annotated with an `id`-keyed upsert, but
    `ReferenceAnalysis` has no `id` — it would have raised `AttributeError` the
    first time the reference node wrote to state. This walks every
    upsert-annotated field and checks the key really exists on the item type,
    so the mistake cannot be made again in a later milestone.
    """

    @staticmethod
    def _upsert_fields() -> list[tuple[str, str, type]]:
        found: list[tuple[str, str, type]] = []
        for name, field in CampaignState.model_fields.items():
            for meta in getattr(field, "metadata", []):
                key = getattr(meta, "upsert_key", None)
                if key is None:
                    continue
                (item_type,) = get_args(field.annotation)
                found.append((name, key, item_type))
        return found

    def test_there_are_upsert_fields_to_check(self) -> None:
        """Names, not a count. A count silently weakens as fields change shape
        — `creative_directions` became the single `direction_set` in Milestone
        5 — whereas a name set says exactly which field left."""
        assert {name for name, _, _ in self._upsert_fields()} == {
            "reference_analysis",
            "model_prompts",
            "generation_jobs",
            "generated_assets",
            "evaluation_results",
            "brand_guardian_results",
            "final_assets",
        }

    def test_every_upsert_key_exists_on_its_item_type(self) -> None:
        for field_name, key, item_type in self._upsert_fields():
            assert key in item_type.model_fields, (
                f"CampaignState.{field_name} upserts on {key!r}, "
                f"but {item_type.__name__} has no such field"
            )

    def test_reference_analysis_upserts_on_its_reference(self) -> None:
        first = ReferenceAnalysis(reference_id="r1", mood=["calm"])
        revised = ReferenceAnalysis(reference_id="r1", mood=["bold"])
        merged = upsert_on("reference_id")([first], [revised])
        assert len(merged) == 1
        assert merged[0].mood == ["bold"]


class TestMergeAndReplace:
    def test_merge_dict_preserves_earlier_gates(self) -> None:
        first = {"strategy": ApprovalDecision(gate=Gate.STRATEGY, decision=Decision.APPROVE)}
        second = {"final": ApprovalDecision(gate=Gate.FINAL, decision=Decision.SELECT)}
        merged = merge_dict(first, second)
        assert set(merged) == {"strategy", "final"}

    def test_merge_dict_does_not_mutate_the_input(self) -> None:
        first = {"strategy": ApprovalDecision(gate=Gate.STRATEGY, decision=Decision.APPROVE)}
        merge_dict(first, {"final": ApprovalDecision(gate=Gate.FINAL, decision=Decision.SELECT)})
        assert set(first) == {"strategy"}


class TestCampaignState:
    def test_initial_state_has_safe_defaults(self) -> None:
        state = initial_state("camp-1", "proj-1", "user-1")
        assert state.iteration_count == 0
        assert state.interview_complete is False
        assert state.errors == [] and state.generated_assets == []
        assert state.campaign_inputs.is_sufficient() is False

    def test_state_is_json_serializable(self) -> None:
        """Non-negotiable: state is checkpointed to Postgres as JSON (ADR-003).
        If this fails, resume-after-restart fails, and the demo with it."""
        state = initial_state("camp-1", "proj-1", "user-1")
        state.conversation = [ConversationTurn(role="user", content="premium campaign")]
        state.generation_jobs = [_job("a")]
        state.errors = [ExecutionError(node="image_generation", code="X", message="y")]

        restored = CampaignState.model_validate(json.loads(state.model_dump_json()))
        assert restored.campaign_id == "camp-1"
        assert restored.generation_jobs[0].idempotency_key == "key-a"

    def test_annotated_reducer_fields_still_validate(self) -> None:
        state = initial_state("camp-1", "proj-1", "user-1")
        with pytest.raises(ValidationError):
            state.generation_jobs = ["not a job"]  # type: ignore[list-item]

    def test_helpers_read_state_without_changing_it(self) -> None:
        state = initial_state("camp-1", "proj-1", "user-1")
        state.errors = [
            ExecutionError(node="n", code="C", message="m", severity="fatal"),
        ]
        state.generation_jobs = [_job("a", JobStatus.FAILED), _job("b", JobStatus.COMPLETED)]

        assert state.has_fatal_error() is True
        assert [j.id for j in state.failed_jobs()] == ["a"]
        assert len(state.assets_for_review()) == 0
        assert state.can_iterate(maximum=8) is True
        assert state.decision_at("strategy") is None

    def test_iteration_guard_stops_runaway_loops(self) -> None:
        state = initial_state("camp-1", "proj-1", "user-1")
        state.iteration_count = 8
        assert state.can_iterate(maximum=8) is False

    def test_interview_and_revision_budgets_are_independent(self) -> None:
        """C-2 regression guard: a long interview must still leave room to
        revise. Sharing one counter meant an 8-turn interview consumed the
        entire revision budget before the first revision existed."""
        state = initial_state("camp-1", "proj-1", "user-1")
        state.interview_turn_count = 8

        assert state.can_ask_another_question(maximum=8) is False
        assert state.can_iterate(maximum=8) is True

    def test_state_fields_snapshot_is_complete(self) -> None:
        """Guards the contract checker: it validates node declarations against
        this set, so an out-of-date set would silently weaken it."""
        assert frozenset(CampaignState.model_fields) == STATE_FIELDS
        for required in ("campaign_brief", "direction_set", "approval_states", "errors"):
            assert required in STATE_FIELDS
