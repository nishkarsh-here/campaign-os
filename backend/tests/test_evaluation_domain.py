"""The evaluation domain: scoring, disposition and ordering.

Every rule here is a pure function of numbers, which is the point — an
evaluation a user cannot recompute is one they cannot argue with. These tests
pin the arithmetic, the thresholds and the tie-breaking so a later change to
any of them is a visible decision rather than a silent drift in what the
product recommends.
"""

from __future__ import annotations

import pytest

from app.domain.evaluation import (
    DEFAULT_THRESHOLDS,
    DIMENSION_GUIDANCE,
    DIMENSION_WEIGHTS,
    EVALUATOR_VERSION,
    CreativeEvaluation,
    Dimension,
    DimensionResult,
    Disposition,
    DispositionThresholds,
    EvaluationSummary,
    RankedAsset,
    Recommendation,
    aggregate_score,
    build_evaluation,
    decide_disposition,
    rank_key,
)

pytestmark = pytest.mark.unit


def _scores(**overrides: int) -> dict[Dimension, int]:
    """A solid, passing asset, adjustable one dimension at a time."""
    base = dict.fromkeys(Dimension, 80)
    for name, value in overrides.items():
        base[Dimension(name)] = value
    return base


def _evaluation(**overrides: int) -> CreativeEvaluation:
    return build_evaluation(
        campaign_id="c1",
        generated_asset_id=overrides.pop("asset_id", "a1"),  # type: ignore[arg-type]
        specification_id="s1",
        specification_version=2,
        scores=_scores(**overrides),
        strengths=["clean composition"],
        concerns=[],
        rationale="Strong overall.",
    )


class TestWeights:
    def test_the_weights_sum_to_one(self) -> None:
        """A weight table that does not sum to 1.0 makes the overall score
        incomparable between evaluations."""
        assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)

    def test_every_dimension_is_weighted(self) -> None:
        assert set(DIMENSION_WEIGHTS) == set(Dimension)

    def test_every_dimension_is_explained(self) -> None:
        """The same words go to the model and to the user, so a dimension with
        no definition would be scored on guesswork."""
        assert set(DIMENSION_GUIDANCE) == set(Dimension)
        assert all(text.strip() for text in DIMENSION_GUIDANCE.values())

    def test_brand_and_campaign_fit_carry_the_most(self) -> None:
        """This is a marketing tool, not a beauty contest."""
        assert (
            DIMENSION_WEIGHTS[Dimension.BRAND_ALIGNMENT]
            > DIMENSION_WEIGHTS[Dimension.VISUAL_QUALITY]
        )
        assert (
            DIMENSION_WEIGHTS[Dimension.CAMPAIGN_OBJECTIVE_FIT]
            > DIMENSION_WEIGHTS[Dimension.VISUAL_QUALITY]
        )


class TestAggregation:
    def test_a_uniform_score_aggregates_to_itself(self) -> None:
        assert aggregate_score(dict.fromkeys(Dimension, 80)) == 80.0

    def test_the_total_is_the_weighted_mean(self) -> None:
        """Worked by hand from the published weights, so the arithmetic is
        pinned rather than asserted against itself."""
        scores = _scores(brand_alignment=100, visual_quality=50)
        # 80 everywhere, +20 on a 0.18 weight, -30 on a 0.10 weight.
        expected = round(80 + 20 * 0.18 - 30 * 0.10, 1)
        assert aggregate_score(scores) == expected == 80.6

    def test_it_is_reproducible(self) -> None:
        scores = _scores(audience_fit=64, composition=91)
        assert aggregate_score(scores) == aggregate_score(scores)

    def test_a_partial_evaluation_renormalises(self) -> None:
        """A degraded evaluation that scored two dimensions must report what it
        measured, not pretend the rest were zero."""
        partial = {Dimension.BRAND_ALIGNMENT: 90, Dimension.VISUAL_QUALITY: 70}
        assert 70 < aggregate_score(partial) < 90

    def test_unknown_dimensions_are_ignored(self) -> None:
        weights = {Dimension.BRAND_ALIGNMENT: 1.0}
        assert aggregate_score(_scores(brand_alignment=42), weights=weights) == 42.0

    def test_no_scores_is_zero_not_a_crash(self) -> None:
        assert aggregate_score({}) == 0.0

    def test_custom_weights_are_honoured(self) -> None:
        """Weights are configuration, so a caller may supply its own."""
        weights = {Dimension.BRAND_ALIGNMENT: 0.5, Dimension.VISUAL_QUALITY: 0.5}
        scores = _scores(brand_alignment=100, visual_quality=0)
        assert aggregate_score(scores, weights=weights) == 50.0


class TestDisposition:
    def test_a_strong_asset_passes(self) -> None:
        scores = _scores()
        disposition, reasons = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.PASS
        assert reasons

    def test_a_weak_overall_score_is_rejected(self) -> None:
        scores = dict.fromkeys(Dimension, 50)
        disposition, reasons = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.REJECT
        assert "below the 55.0 threshold" in reasons[0]

    def test_a_strong_asset_with_one_critical_weakness_needs_review(self) -> None:
        """The case the thresholds exist for: a beautiful plate that is
        off-brand is not a pass."""
        scores = _scores(brand_alignment=55)
        overall = aggregate_score(scores)
        assert overall > DEFAULT_THRESHOLDS.pass_at, "still a strong total"

        disposition, reasons = decide_disposition(scores, overall)
        assert disposition is Disposition.NEEDS_REVIEW
        assert "Brand alignment" in reasons[0]

    def test_a_critically_weak_dimension_is_fatal_on_its_own(self) -> None:
        scores = _scores(brand_alignment=20)
        disposition, reasons = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.REJECT
        assert "critically weak" in reasons[0]

    def test_a_middling_asset_needs_review(self) -> None:
        scores = dict.fromkeys(Dimension, 65)
        disposition, reasons = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.NEEDS_REVIEW
        assert "below the 72.0 pass mark" in reasons[0]

    def test_a_non_critical_weakness_does_not_block_a_pass(self) -> None:
        """Only the critical dimensions hold a veto; the rest are absorbed by
        the weighted mean."""
        scores = _scores(regional_fit=10)
        disposition, _ = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.PASS

    def test_plate_readiness_is_critical(self) -> None:
        """An image that already carries text is not usable as a plate,
        however good it looks (ADR-006)."""
        scores = _scores(plate_readiness=30)
        disposition, _ = decide_disposition(scores, aggregate_score(scores))
        assert disposition is Disposition.REJECT

    @pytest.mark.parametrize(
        ("overall", "expected"),
        [
            (54.9, Disposition.REJECT),
            (55.0, Disposition.NEEDS_REVIEW),
            (71.9, Disposition.NEEDS_REVIEW),
            (72.0, Disposition.PASS),
        ],
    )
    def test_the_boundaries_are_exact(self, overall, expected) -> None:
        """Off-by-one at a threshold changes what the product recommends."""
        disposition, _ = decide_disposition(_scores(), overall)
        assert disposition is expected

    def test_thresholds_can_be_overridden(self) -> None:
        strict = DispositionThresholds(reject_below=60, pass_at=95)
        disposition, _ = decide_disposition(
            _scores(), aggregate_score(_scores()), thresholds=strict
        )
        assert disposition is Disposition.NEEDS_REVIEW

    def test_incoherent_thresholds_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="pass_at must be above"):
            DispositionThresholds(reject_below=80, pass_at=70)
        with pytest.raises(ValueError, match="critical_reject_floor must be below"):
            DispositionThresholds(critical_floor=30, critical_reject_floor=40)

    def test_a_disposition_always_explains_itself(self) -> None:
        for scores in (_scores(), _scores(brand_alignment=20), dict.fromkeys(Dimension, 60)):
            _, reasons = decide_disposition(scores, aggregate_score(scores))
            assert reasons, "a disposition with no stated reason cannot be argued with"


class TestTheOverallScoreCannotBeFaked:
    def test_building_computes_the_total(self) -> None:
        evaluation = _evaluation()
        assert evaluation.overall_score == aggregate_score(evaluation.score_map())

    def test_an_inconsistent_total_is_rejected(self) -> None:
        """The guard that stops a model — or a future shortcut — inventing a
        score that does not follow from its own dimensions."""
        with pytest.raises(ValueError, match="does not follow"):
            CreativeEvaluation(
                campaign_id="c1",
                generated_asset_id="a1",
                specification_id="s1",
                dimensions=[
                    DimensionResult(dimension=Dimension.BRAND_ALIGNMENT, score=10),
                ],
                overall_score=99.0,
                disposition=Disposition.PASS,
            )

    def test_a_dimension_cannot_be_scored_twice(self) -> None:
        with pytest.raises(ValueError, match="only be scored once"):
            CreativeEvaluation(
                campaign_id="c1",
                generated_asset_id="a1",
                specification_id="s1",
                dimensions=[
                    DimensionResult(dimension=Dimension.BRAND_ALIGNMENT, score=80),
                    DimensionResult(dimension=Dimension.BRAND_ALIGNMENT, score=20),
                ],
                overall_score=80.0,
                disposition=Disposition.PASS,
            )

    def test_a_score_outside_the_scale_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            DimensionResult(dimension=Dimension.BRAND_ALIGNMENT, score=101)
        with pytest.raises(ValueError):
            DimensionResult(dimension=Dimension.BRAND_ALIGNMENT, score=-1)


class TestProvenance:
    def test_the_evaluator_version_is_recorded(self) -> None:
        assert _evaluation().evaluator_version == EVALUATOR_VERSION

    def test_the_source_specification_version_is_recorded(self) -> None:
        """Milestone 8 needs to know which plan an asset was judged against."""
        evaluation = _evaluation()
        assert evaluation.specification_version == 2
        assert evaluation.specification_id == "s1"

    def test_concerns_survive_for_a_later_revision(self) -> None:
        evaluation = build_evaluation(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            specification_version=1,
            scores=_scores(audience_fit=40),
            strengths=[],
            concerns=["Reads as consumer advertising, not specification material."],
            rationale="Weak audience fit.",
        )
        assert evaluation.concerns == ["Reads as consumer advertising, not specification material."]

    def test_summaries_are_capped_not_essays(self) -> None:
        """Concise explanations only — never a reasoning trace."""
        evaluation = build_evaluation(
            campaign_id="c1",
            generated_asset_id="a1",
            specification_id="s1",
            specification_version=1,
            scores=_scores(),
            strengths=[f"strength {i}" for i in range(9)],
            concerns=[f"concern {i}" for i in range(9)],
            rationale="ok",
        )
        assert len(evaluation.strengths) == 4
        assert len(evaluation.concerns) == 4


class TestOrdering:
    def test_the_higher_score_ranks_first(self) -> None:
        strong = _evaluation(asset_id="a", brand_alignment=95)
        weak = _evaluation(asset_id="b", brand_alignment=60)
        assert sorted([weak, strong], key=rank_key)[0] is strong

    def test_a_tie_breaks_on_brand_alignment(self) -> None:
        """Two assets with the same total are separated by what matters most."""
        # Swap 10 points between two equally weighted dimensions: same total.
        first = _evaluation(asset_id="a", brand_alignment=90, campaign_objective_fit=70)
        second = _evaluation(asset_id="b", brand_alignment=70, campaign_objective_fit=90)
        assert first.overall_score == second.overall_score

        assert sorted([second, first], key=rank_key)[0] is first

    def test_a_further_tie_breaks_on_campaign_fit(self) -> None:
        """Equal totals and equal brand alignment: campaign fit decides.

        +10 on campaign fit (weight 0.18) is offset by -15 on audience fit
        (weight 0.12), so both assets total exactly 80.
        """
        first = _evaluation(asset_id="a", campaign_objective_fit=90, audience_fit=65)
        second = _evaluation(asset_id="b")
        assert first.overall_score == second.overall_score == 80.0
        assert first.score_for(Dimension.BRAND_ALIGNMENT) == second.score_for(
            Dimension.BRAND_ALIGNMENT
        )
        assert sorted([second, first], key=rank_key)[0] is first

    def test_a_complete_tie_falls_back_to_the_asset_id(self) -> None:
        """The ordering must be total, or the same evaluations would render in
        a different order between page loads."""
        first = _evaluation(asset_id="aaa")
        second = _evaluation(asset_id="bbb")
        assert rank_key(first) < rank_key(second)
        assert [e.generated_asset_id for e in sorted([second, first], key=rank_key)] == [
            "aaa",
            "bbb",
        ]

    def test_ordering_is_stable_across_input_order(self) -> None:
        evaluations = [
            _evaluation(asset_id="a", brand_alignment=70),
            _evaluation(asset_id="b", brand_alignment=90),
            _evaluation(asset_id="c", brand_alignment=90),
        ]
        forward = [e.generated_asset_id for e in sorted(evaluations, key=rank_key)]
        backward = [e.generated_asset_id for e in sorted(reversed(evaluations), key=rank_key)]
        assert forward == backward == ["b", "c", "a"]


class TestSummary:
    def test_it_reports_a_complete_batch(self) -> None:
        summary = EvaluationSummary(
            campaign_id="c1",
            ranked=[
                RankedAsset(
                    generated_asset_id="a",
                    evaluation_id="e",
                    rank=1,
                    overall_score=80.0,
                    disposition=Disposition.PASS,
                )
            ],
        )
        assert summary.outcome() == "All 1 asset evaluated."

    def test_it_reports_partial_success(self) -> None:
        """A batch where one evaluation failed is still useful, and says so."""
        summary = EvaluationSummary(
            campaign_id="c1",
            ranked=[
                RankedAsset(
                    generated_asset_id=name,
                    evaluation_id="e",
                    rank=index + 1,
                    overall_score=80.0,
                    disposition=Disposition.PASS,
                )
                for index, name in enumerate(("a", "b"))
            ],
            failed_asset_ids=["c"],
        )
        assert summary.outcome() == "2/3 assets evaluated — 1 failed."

    def test_nothing_evaluated_says_so(self) -> None:
        assert EvaluationSummary(campaign_id="c1").outcome() == "Nothing evaluated yet."

    def test_a_recommendation_can_be_empty(self) -> None:
        """When every asset was rejected there is nothing to recommend, and
        inventing one would be worse than saying so."""
        recommendation = Recommendation(reason="No asset met the bar.")
        assert recommendation.generated_asset_id is None
