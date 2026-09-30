"""Which stage the command centre nominates as next.

Audit finding DH-1. A pure function over the stage list, so every combination
that mattered can be stated rather than seeded: the defect was a campaign whose
only unfinished stages were `RUNNING` and `BLOCKED`, which produced no next
stage at all and made the workspace announce "This campaign is complete."

The table below is the contract. `None` means finished, and only a wholly
finished campaign may produce it.
"""

from __future__ import annotations

import pytest

from app.services.overview import (
    ATTENTION,
    BLOCKED,
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    StageState,
    next_unfinished_stage,
)

pytestmark = pytest.mark.unit

#: The real pipeline order, which is what makes "the first one" meaningful.
KEYS = ("discovery", "creative", "generation", "evaluation", "guardian", "composition")


def _stages(*states: str) -> list[StageState]:
    assert len(states) == len(KEYS)
    return [
        StageState(key=key, label=key.title(), state=state, detail=f"{key} is {state.lower()}")
        for key, state in zip(KEYS, states, strict=True)
    ]


class TestTheDefect:
    def test_a_running_generation_is_not_a_finished_campaign(self) -> None:
        """The exact state that reported completion: generation in flight, with
        everything after it blocked behind it."""
        stages = _stages(DONE, DONE, RUNNING, BLOCKED, BLOCKED, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None, "a campaign mid-generation is not complete"
        assert nxt.key == "generation"
        assert nxt.state == RUNNING

    def test_a_running_evaluation_is_not_a_finished_campaign(self) -> None:
        stages = _stages(DONE, DONE, DONE, RUNNING, BLOCKED, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None and nxt.key == "evaluation"

    def test_a_running_brand_check_is_not_a_finished_campaign(self) -> None:
        stages = _stages(DONE, DONE, DONE, DONE, RUNNING, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None and nxt.key == "guardian"

    def test_a_blocked_tail_is_not_a_finished_campaign(self) -> None:
        """No stage `RUNNING`, nothing `PENDING`, and still not finished."""
        stages = _stages(DONE, DONE, DONE, BLOCKED, BLOCKED, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None and nxt.state == BLOCKED


class TestOnlyAFinishedCampaignIsFinished:
    def test_every_stage_done_reports_nothing_next(self) -> None:
        assert next_unfinished_stage(_stages(*[DONE] * 6)) is None

    @pytest.mark.parametrize("state", [PENDING, BLOCKED, ATTENTION, RUNNING, FAILED])
    def test_one_unfinished_stage_anywhere_is_reported(self, state: str) -> None:
        """Whichever slot it sits in. This is the property the workspace's
        "complete" branch depends on being total."""
        for position in range(len(KEYS)):
            states = [DONE] * len(KEYS)
            states[position] = state
            nxt = next_unfinished_stage(_stages(*states))
            assert nxt is not None, f"{state} at {KEYS[position]} must be reported"
            assert nxt.key == KEYS[position]


class TestItPicksTheEarliestUnfinishedStage:
    def test_a_failure_behind_a_pending_stage_is_not_jumped_to(self) -> None:
        """Pipeline order, not severity. A stage cannot be acted on before the
        one it depends on, so the earliest is the only useful answer."""
        stages = _stages(DONE, PENDING, FAILED, BLOCKED, BLOCKED, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None and nxt.key == "creative"

    def test_the_first_stage_wins_when_discovery_has_not_started(self) -> None:
        stages = _stages(PENDING, BLOCKED, BLOCKED, BLOCKED, BLOCKED, BLOCKED)

        nxt = next_unfinished_stage(stages)

        assert nxt is not None and nxt.key == "discovery"


class TestTheDetailTravelsWithIt:
    def test_the_nominated_stage_carries_its_own_sentence(self) -> None:
        """The workspace renders this verbatim rather than paraphrasing, so an
        empty detail would leave the card with nothing to say."""
        nxt = next_unfinished_stage(_stages(DONE, DONE, RUNNING, BLOCKED, BLOCKED, BLOCKED))

        assert nxt is not None
        assert nxt.detail == "generation is running"


class TestAnEmptyListIsNotAFinishedCampaign:
    def test_no_stages_reports_nothing_next(self) -> None:
        """Degenerate, and worth pinning: the overview always builds six, so if
        this is ever reached something else is wrong and "complete" would be the
        wrong thing to show."""
        assert next_unfinished_stage([]) is None
