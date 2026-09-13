"""Ranking and recommendation.

A pure function of the stored evaluations. Nothing here calls a model, reads a
clock or touches the database — give it the same evaluations in any order and
it returns the same ranking, which is why no ranking is persisted: a stored
ranking would be a second source of truth free to fall out of step with the
evaluations it claims to summarise.

The recommendation is advice, never a decision. A human selects, and the
recommendation says plainly when the best available asset is not actually good
enough — a system that always names a winner teaches people to ignore it.
"""

from __future__ import annotations

from app.domain.evaluation import (
    CreativeEvaluation,
    Dimension,
    Disposition,
    EvaluationSummary,
    RankedAsset,
    Recommendation,
    rank_key,
)

#: Dispositions worth recommending, best first. A `NEEDS_REVIEW` asset is
#: offered only when nothing passed — with the caveat saying so.
RECOMMENDABLE: tuple[Disposition, ...] = (Disposition.PASS, Disposition.NEEDS_REVIEW)


def rank(evaluations: list[CreativeEvaluation]) -> list[RankedAsset]:
    """Order the evaluations and number them.

    Sorted by `rank_key`: overall score, then brand alignment, then campaign
    fit, then asset id. The trailing id makes the ordering *total*, so two
    assets identical on every score still render in the same sequence on every
    page load.
    """
    ordered = sorted(evaluations, key=rank_key)
    best = ordered[0] if ordered else None
    recommended_id = best.generated_asset_id if best and _is_recommendable(best) else None

    return [
        RankedAsset(
            generated_asset_id=evaluation.generated_asset_id,
            evaluation_id=evaluation.id,
            rank=index + 1,
            overall_score=evaluation.overall_score,
            disposition=evaluation.disposition,
            reason=_reason(evaluation),
            recommended=evaluation.generated_asset_id == recommended_id,
        )
        for index, evaluation in enumerate(ordered)
    ]


def recommend(evaluations: list[CreativeEvaluation]) -> Recommendation:
    """The one to put forward, and why.

    Picks the best *recommendable* asset rather than simply the top of the
    ranking: an asset the rules rejected should not be presented as the
    system's suggestion just because everything else scored worse.
    """
    if not evaluations:
        return Recommendation(reason="Nothing has been evaluated yet.")

    ordered = sorted(evaluations, key=rank_key)
    eligible = [e for e in ordered if _is_recommendable(e)]
    if not eligible:
        return Recommendation(
            reason="No creative met the bar. Every asset was rejected.",
            caveat=(
                "Generating again from the approved specification is likely to be "
                "more useful than picking the least weak of these."
            ),
        )

    best = eligible[0]
    rank_of = {e.generated_asset_id: i + 1 for i, e in enumerate(ordered)}
    return Recommendation(
        generated_asset_id=best.generated_asset_id,
        rank=rank_of[best.generated_asset_id],
        overall_score=best.overall_score,
        reason=_reason(best),
        caveat=_caveat(best, eligible_count=len(eligible), total=len(ordered)),
    )


def summarise(
    campaign_id: str,
    evaluations: list[CreativeEvaluation],
    *,
    failed_asset_ids: list[str] | None = None,
    selected_asset_id: str | None = None,
    evaluator_version: str | None = None,
) -> EvaluationSummary:
    """Everything the recommendation screen reads, in one object."""
    ranked = rank(evaluations)
    summary = EvaluationSummary(
        campaign_id=campaign_id,
        ranked=ranked,
        recommendation=recommend(evaluations),
        failed_asset_ids=list(failed_asset_ids or []),
        selected_asset_id=selected_asset_id,
    )
    if evaluator_version is not None:
        summary.evaluator_version = evaluator_version
    return summary


def _is_recommendable(evaluation: CreativeEvaluation) -> bool:
    return evaluation.disposition in RECOMMENDABLE


def _reason(evaluation: CreativeEvaluation) -> str:
    """One sentence naming what carried this asset, and what held it back.

    Built from the dimension scores rather than from the model's prose, so the
    explanation is always consistent with the numbers beside it — and never a
    reasoning trace.
    """
    scores = evaluation.score_map()
    if not scores:
        return "No dimensions were scored."

    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0].value))
    strongest, strongest_score = ordered[0]
    weakest, weakest_score = ordered[-1]

    lead = f"Strongest on {_label(strongest)} ({strongest_score})"
    if evaluation.disposition is Disposition.REJECT:
        return f"{lead}, but {_label(weakest).lower()} ({weakest_score}) puts it out of contention."
    if weakest_score < 65:
        return f"{lead}; weaker on {_label(weakest).lower()} ({weakest_score})."
    return f"{lead}, with no weak dimension."


def _caveat(evaluation: CreativeEvaluation, *, eligible_count: int, total: int) -> str | None:
    """Said out loud when the recommendation deserves a second look."""
    if evaluation.disposition is Disposition.NEEDS_REVIEW:
        return "Nothing passed outright — this is the strongest of the assets needing review."
    if eligible_count == 1 and total > 1:
        return "The only asset that cleared the bar."
    return None


def _label(dimension: Dimension) -> str:
    return dimension.value.replace("_", " ").capitalize()
