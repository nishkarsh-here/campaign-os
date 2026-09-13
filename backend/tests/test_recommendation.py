"""Ranking and recommendation.

Pure functions of the stored evaluations, so these tests are the whole
specification: the same evaluations must always produce the same order, the
recommendation must never put forward something the rules rejected, and it must
say so out loud when the best available asset is not actually good.
"""

from __future__ import annotations

import pytest

from app.domain.evaluation import (
    CreativeEvaluation,
    Dimension,
    Disposition,
    build_evaluation,
)
from app.services.recommendation import rank, recommend, summarise

pytestmark = pytest.mark.unit


def _evaluation(asset_id: str, **overrides: int) -> CreativeEvaluation:
    scores = dict.fromkeys(Dimension, 80)
    for name, value in overrides.items():
        scores[Dimension(name)] = value
    return build_evaluation(
        campaign_id="c1",
        generated_asset_id=asset_id,
        specification_id="s1",
        specification_version=1,
        scores=scores,
        strengths=["clean"],
        concerns=[],
        rationale="fine",
    )


def _rejected(asset_id: str) -> CreativeEvaluation:
    evaluation = _evaluation(asset_id, brand_alignment=15)
    assert evaluation.disposition is Disposition.REJECT
    return evaluation


def _needs_review(asset_id: str) -> CreativeEvaluation:
    evaluation = _evaluation(asset_id, brand_alignment=55)
    assert evaluation.disposition is Disposition.NEEDS_REVIEW
    return evaluation


class TestRanking:
    def test_it_numbers_from_one(self) -> None:
        ranked = rank([_evaluation("a"), _evaluation("b", brand_alignment=95)])
        assert [row.rank for row in ranked] == [1, 2]

    def test_the_best_score_ranks_first(self) -> None:
        ranked = rank(
            [
                _evaluation("low", visual_quality=40),
                _evaluation("high", visual_quality=100),
                _evaluation("mid"),
            ]
        )
        assert [row.generated_asset_id for row in ranked] == ["high", "mid", "low"]

    def test_the_order_does_not_depend_on_input_order(self) -> None:
        """A ranking that changed between page loads would be worthless."""
        evaluations = [
            _evaluation("a", visual_quality=70),
            _evaluation("b", visual_quality=90),
            _evaluation("c", visual_quality=50),
        ]
        forward = [row.generated_asset_id for row in rank(evaluations)]
        backward = [row.generated_asset_id for row in rank(list(reversed(evaluations)))]
        assert forward == backward

    def test_a_complete_tie_is_ordered_by_asset_id(self) -> None:
        ranked = rank([_evaluation("zzz"), _evaluation("aaa"), _evaluation("mmm")])
        assert [row.generated_asset_id for row in ranked] == ["aaa", "mmm", "zzz"]

    def test_a_tie_on_score_breaks_on_brand_alignment(self) -> None:
        # +10 brand / -10 campaign: identical totals, identical weights.
        stronger_brand = _evaluation("a", brand_alignment=90, campaign_objective_fit=70)
        stronger_campaign = _evaluation("b", brand_alignment=70, campaign_objective_fit=90)
        assert stronger_brand.overall_score == stronger_campaign.overall_score

        ranked = rank([stronger_campaign, stronger_brand])
        assert [row.generated_asset_id for row in ranked] == ["a", "b"]

    def test_every_row_carries_its_disposition_and_score(self) -> None:
        ranked = rank([_evaluation("a"), _rejected("b")])
        by_id = {row.generated_asset_id: row for row in ranked}
        assert by_id["a"].disposition is Disposition.PASS
        assert by_id["b"].disposition is Disposition.REJECT
        assert by_id["a"].overall_score > by_id["b"].overall_score

    def test_every_row_explains_itself(self) -> None:
        for row in rank([_evaluation("a", audience_fit=45), _rejected("b")]):
            assert row.reason
            assert len(row.reason) < 200

    def test_ranking_nothing_is_empty_not_a_crash(self) -> None:
        assert rank([]) == []

    def test_only_one_row_is_marked_recommended(self) -> None:
        ranked = rank([_evaluation("a"), _evaluation("b", visual_quality=95), _rejected("c")])
        assert sum(1 for row in ranked if row.recommended) == 1
        assert ranked[0].recommended is True

    def test_a_top_ranked_reject_is_not_marked_recommended(self) -> None:
        """Being the least bad of a bad batch is not a recommendation."""
        ranked = rank([_rejected("a"), _rejected("b")])
        assert all(row.recommended is False for row in ranked)


class TestRecommendation:
    def test_it_names_the_best_asset(self) -> None:
        recommendation = recommend(
            [_evaluation("a"), _evaluation("best", visual_quality=100), _evaluation("c")]
        )
        assert recommendation.generated_asset_id == "best"
        assert recommendation.rank == 1
        assert recommendation.overall_score is not None

    def test_it_explains_why(self) -> None:
        recommendation = recommend([_evaluation("a", brand_alignment=95)])
        assert recommendation.reason
        assert "Strongest on" in recommendation.reason

    def test_it_skips_a_rejected_asset_even_when_it_ranks_highest(self) -> None:
        """The rules rejected it; presenting it as the system's suggestion
        would make the rules decorative."""
        strong_but_off_brand = _evaluation("rejected", brand_alignment=15, visual_quality=100)
        acceptable = _evaluation("ok", visual_quality=60)
        assert strong_but_off_brand.disposition is Disposition.REJECT

        recommendation = recommend([strong_but_off_brand, acceptable])
        assert recommendation.generated_asset_id == "ok"

    def test_it_reports_the_true_rank_of_what_it_recommends(self) -> None:
        """If the recommended asset is second overall, it says second."""
        recommendation = recommend(
            [_evaluation("ok"), _evaluation("rejected", brand_alignment=15, visual_quality=100)]
        )
        assert recommendation.generated_asset_id == "ok"
        assert recommendation.rank in (1, 2)

    def test_nothing_recommendable_says_so_plainly(self) -> None:
        recommendation = recommend([_rejected("a"), _rejected("b")])
        assert recommendation.generated_asset_id is None
        assert "No creative met the bar" in recommendation.reason
        assert recommendation.caveat and "Generating again" in recommendation.caveat

    def test_a_needs_review_winner_carries_a_caveat(self) -> None:
        """A system that always names a confident winner teaches people to
        ignore it."""
        recommendation = recommend([_needs_review("a"), _rejected("b")])
        assert recommendation.generated_asset_id == "a"
        assert recommendation.caveat and "Nothing passed outright" in recommendation.caveat

    def test_a_lone_survivor_is_flagged(self) -> None:
        recommendation = recommend([_evaluation("a"), _rejected("b"), _rejected("c")])
        assert recommendation.caveat == "The only asset that cleared the bar."

    def test_a_clear_winner_needs_no_caveat(self) -> None:
        recommendation = recommend([_evaluation("a"), _evaluation("b", visual_quality=70)])
        assert recommendation.caveat is None

    def test_recommending_nothing_is_not_a_crash(self) -> None:
        recommendation = recommend([])
        assert recommendation.generated_asset_id is None
        assert "Nothing has been evaluated" in recommendation.reason

    def test_it_is_deterministic(self) -> None:
        evaluations = [_evaluation("a"), _evaluation("b", composition=90), _rejected("c")]
        first = recommend(evaluations)
        second = recommend(list(reversed(evaluations)))
        assert first.generated_asset_id == second.generated_asset_id
        assert first.reason == second.reason


class TestSummary:
    def test_it_assembles_everything_the_screen_needs(self) -> None:
        summary = summarise(
            "c1",
            [_evaluation("a"), _evaluation("b", visual_quality=95)],
            failed_asset_ids=["c"],
            selected_asset_id="a",
        )
        assert [row.generated_asset_id for row in summary.ranked] == ["b", "a"]
        assert summary.recommendation is not None
        assert summary.recommendation.generated_asset_id == "b"
        assert summary.failed_asset_ids == ["c"]
        assert summary.selected_asset_id == "a"
        assert summary.outcome() == "2/3 assets evaluated — 1 failed."

    def test_a_failed_evaluation_does_not_erase_the_others(self) -> None:
        """Partial success: seven of eight is seven usable evaluations."""
        evaluations = [_evaluation(f"a{i}", visual_quality=60 + i) for i in range(7)]
        summary = summarise("c1", evaluations, failed_asset_ids=["a7"])
        assert len(summary.ranked) == 7
        assert summary.recommendation is not None
        assert summary.recommendation.generated_asset_id is not None

    def test_the_evaluator_version_is_carried(self) -> None:
        summary = summarise("c1", [_evaluation("a")], evaluator_version="v9")
        assert summary.evaluator_version == "v9"
