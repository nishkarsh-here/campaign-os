"""The Creative Evaluator.

Answers "how good is this creative?" with scores and a ranking. The companion
question — "is this acceptable for this brand?" — is the Brand Guardian's, and
lives in `app.domain.guardian`. They are separate modules because conflating
them is the classic mistake: a beautiful creative that implies a prohibited
claim must fail, and a merely adequate one that is perfectly on-brand must pass.
Ranking uses the score; the guardian holds a veto.

**The evaluator assesses; it never creates.** It may say keep, revise or reject,
and it may say why — but it never rewrites a prompt or a specification. Any
actual revision belongs to Milestone 8.

**The model scores dimensions; this module computes the total.** A model asked
for an overall score will produce one that does not follow from its own
dimension scores, and then nothing can be explained or tested.
`aggregate_score` and `decide_disposition` are pure functions of the dimension
scores and the weights below, so a total is always reproducible and a
disposition is always arguable from the numbers.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from app.domain.common import DomainModel, Id, new_id, utc_now

#: Bumped whenever the dimensions, weights or thresholds change. Recorded on
#: every evaluation so results from different criteria are never silently
#: compared as though they were equivalent.
EVALUATOR_VERSION = "v1"

#: A dimension score. Integer 0-100: a model asked for one decimal place
#: produces false precision, and ranking never needs it.
DimensionScore = Annotated[int, Field(ge=0, le=100)]


class Dimension(StrEnum):
    """What a creative is judged on.

    Ten, and no more. Each one has to be something a human would actually
    argue about in a review; a long tail of invented metrics makes an
    evaluation harder to read and no more accurate.
    """

    BRAND_ALIGNMENT = "brand_alignment"
    CAMPAIGN_OBJECTIVE_FIT = "campaign_objective_fit"
    AUDIENCE_FIT = "audience_fit"
    CREATIVE_DIRECTION_ALIGNMENT = "creative_direction_alignment"
    VISUAL_QUALITY = "visual_quality"
    COMPOSITION = "composition"
    PRODUCT_REPRESENTATION = "product_representation"
    REGIONAL_FIT = "regional_fit"
    REFERENCE_STYLE_ALIGNMENT = "reference_style_alignment"
    PLATE_READINESS = "plate_readiness"


#: What each dimension means, in the words the model is given and the words a
#: user reads. One definition, so the prompt and the UI cannot drift apart.
DIMENSION_GUIDANCE: dict[Dimension, str] = {
    Dimension.BRAND_ALIGNMENT: (
        "Does this look like it belongs to this brand — its tone, its restraint, "
        "its colour world? Not whether the logo is present; the logo is added later."
    ),
    Dimension.CAMPAIGN_OBJECTIVE_FIT: (
        "Does this image advance what the campaign is trying to achieve?"
    ),
    Dimension.AUDIENCE_FIT: (
        "Would the stated audience recognise this as made for them, and take it seriously?"
    ),
    Dimension.CREATIVE_DIRECTION_ALIGNMENT: (
        "Is this the approved direction — its subject, setting, framing and light — "
        "or has it drifted into a different idea?"
    ),
    Dimension.VISUAL_QUALITY: (
        "Craft: is it clean, believable and free of artefacts, malformed detail or mush?"
    ),
    Dimension.COMPOSITION: (
        "Does the eye land where it should, and is there a clear hierarchy rather "
        "than an even field of clutter?"
    ),
    Dimension.PRODUCT_REPRESENTATION: (
        "Is the product shown accurately and advantageously, and is it the subject "
        "rather than a prop?"
    ),
    Dimension.REGIONAL_FIT: (
        "Does it read correctly for the stated region? Score 50 — neither credit nor "
        "penalty — if the campaign states no region."
    ),
    Dimension.REFERENCE_STYLE_ALIGNMENT: (
        "Does it hit the intended abstract style characteristics — premium, minimal, "
        "technical, cinematic, editorial, and the intended lighting and density? "
        "Never whether it resembles a specific reference image."
    ),
    Dimension.PLATE_READINESS: (
        "Is this usable as a VISUAL PLATE for downstream composition? It needs a quiet, "
        "even area where a headline and call to action will be placed, and it must not "
        "already contain text, lettering or a logo. Rendered text in the image is a "
        "defect here, never a bonus — the brand renderer sets type, not the model."
    ),
}

#: Weights sum to 1.0; asserted in tests so a future edit cannot silently skew
#: ranking. Brand alignment and campaign fit dominate on purpose — this is a
#: marketing tool, not a beauty contest, and the prettiest plate that misses the
#: objective is the wrong answer.
DIMENSION_WEIGHTS: dict[Dimension, float] = {
    Dimension.BRAND_ALIGNMENT: 0.18,
    Dimension.CAMPAIGN_OBJECTIVE_FIT: 0.18,
    Dimension.AUDIENCE_FIT: 0.12,
    Dimension.CREATIVE_DIRECTION_ALIGNMENT: 0.12,
    Dimension.VISUAL_QUALITY: 0.10,
    Dimension.COMPOSITION: 0.08,
    Dimension.PRODUCT_REPRESENTATION: 0.08,
    Dimension.PLATE_READINESS: 0.06,
    Dimension.REFERENCE_STYLE_ALIGNMENT: 0.04,
    Dimension.REGIONAL_FIT: 0.04,
}


class Disposition(StrEnum):
    """What should happen to this asset.

    Derived from thresholds rather than asked of the model: a disposition that
    did not follow from the scores could not be argued with, and could not be
    tested.
    """

    PASS = "PASS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECT = "REJECT"


class DispositionThresholds(DomainModel):
    """The rules that turn scores into a decision.

    In one place, versioned with the evaluator, and tested — so "why was this
    rejected?" has an answer that does not require reading a model's mind.
    """

    #: Below this overall score nothing is salvageable.
    reject_below: float = Field(default=55.0, ge=0, le=100)
    #: At or above this, and with no critical weakness, an asset passes.
    pass_at: float = Field(default=72.0, ge=0, le=100)
    #: Dimensions where a weakness matters regardless of the total. A gorgeous
    #: plate that is off-brand is not a pass.
    critical: tuple[Dimension, ...] = (
        Dimension.BRAND_ALIGNMENT,
        Dimension.CAMPAIGN_OBJECTIVE_FIT,
        Dimension.PLATE_READINESS,
    )
    #: A critical dimension under this drags an otherwise strong asset to review.
    critical_floor: int = Field(default=60, ge=0, le=100)
    #: A critical dimension under this is fatal on its own.
    critical_reject_floor: int = Field(default=35, ge=0, le=100)

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> DispositionThresholds:
        if self.pass_at <= self.reject_below:
            raise ValueError("pass_at must be above reject_below")
        if self.critical_reject_floor >= self.critical_floor:
            raise ValueError("critical_reject_floor must be below critical_floor")
        return self


#: The active rules. A caller may pass its own for testing or for a future
#: per-brand policy; nothing reads a global at judgement time.
DEFAULT_THRESHOLDS = DispositionThresholds()


def aggregate_score(
    scores: dict[Dimension, int], *, weights: dict[Dimension, float] | None = None
) -> float:
    """The weighted mean, to one decimal place.

    Renormalised over the dimensions actually present, so a degraded evaluation
    that scored six dimensions reports what it measured rather than pretending
    the other four were zero. Pure: the same scores and weights always give the
    same number, which is what makes a total explainable.
    """
    table = weights or DIMENSION_WEIGHTS
    total = 0.0
    used = 0.0
    for dimension, score in scores.items():
        weight = table.get(dimension)
        if weight is None:
            continue
        total += score * weight
        used += weight
    return round(total / used, 1) if used else 0.0


def decide_disposition(
    scores: dict[Dimension, int],
    overall: float,
    *,
    thresholds: DispositionThresholds | None = None,
) -> tuple[Disposition, list[str]]:
    """The decision, and the rules that produced it.

    Returns the reasons as well as the verdict: a disposition a user cannot
    interrogate is indistinguishable from a guess. Rules are checked in order
    of severity, and the first that fires decides.
    """
    rules = thresholds or DEFAULT_THRESHOLDS
    reasons: list[str] = []

    fatal = [
        dimension
        for dimension in rules.critical
        if scores.get(dimension, 100) < rules.critical_reject_floor
    ]
    if fatal:
        reasons.extend(f"{_label(d)} is critically weak ({scores[d]})" for d in fatal)
        return Disposition.REJECT, reasons

    if overall < rules.reject_below:
        reasons.append(f"Overall {overall} is below the {rules.reject_below} threshold")
        return Disposition.REJECT, reasons

    weak = [
        dimension
        for dimension in rules.critical
        if scores.get(dimension, 100) < rules.critical_floor
    ]
    if weak:
        reasons.extend(
            f"{_label(d)} is below the {rules.critical_floor} floor ({scores[d]})" for d in weak
        )
        return Disposition.NEEDS_REVIEW, reasons

    if overall >= rules.pass_at:
        reasons.append(f"Overall {overall} with no critical weakness")
        return Disposition.PASS, reasons

    reasons.append(f"Overall {overall} is below the {rules.pass_at} pass mark")
    return Disposition.NEEDS_REVIEW, reasons


def _label(dimension: Dimension) -> str:
    return dimension.value.replace("_", " ").capitalize()


class DimensionResult(DomainModel):
    """One dimension's score and the one line explaining it."""

    dimension: Dimension
    score: DimensionScore
    #: One sentence, user-facing. Never reasoning traces (CLAUDE.md rule 8).
    note: str = Field(default="", max_length=300)


class CreativeEvaluation(DomainModel):
    """One asset, judged against the plan it was generated from."""

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    generated_asset_id: Id
    #: The plan this asset came from. An asset is always judged against its own
    #: source version, never against a specification approved afterwards.
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    evaluator_version: str = EVALUATOR_VERSION
    #: Which model produced the qualitative judgement, for the record.
    evaluator_model: str | None = None

    dimensions: list[DimensionResult] = Field(min_length=1)
    #: Computed here from `dimensions`, never taken from the model.
    overall_score: float = Field(ge=0, le=100)
    disposition: Disposition
    #: The threshold rules that produced the disposition, in words.
    disposition_reasons: list[str] = Field(default_factory=list, max_length=6)

    strengths: list[str] = Field(default_factory=list, max_length=4)
    concerns: list[str] = Field(default_factory=list, max_length=4)
    #: One or two sentences a human reads. Not a reasoning trace.
    rationale: str = Field(default="", max_length=600)
    evaluated_at: datetime = Field(default_factory=utc_now)

    def score_map(self) -> dict[Dimension, int]:
        return {result.dimension: result.score for result in self.dimensions}

    def score_for(self, dimension: Dimension) -> int:
        """Missing dimensions score 0 for *ordering* purposes only — never for
        the overall score, which renormalises instead."""
        return self.score_map().get(dimension, 0)

    @model_validator(mode="after")
    def _no_duplicate_dimensions(self) -> CreativeEvaluation:
        seen = [result.dimension for result in self.dimensions]
        if len(seen) != len(set(seen)):
            raise ValueError("A dimension may only be scored once")
        return self

    @model_validator(mode="after")
    def _overall_follows_from_the_dimensions(self) -> CreativeEvaluation:
        """The guard that keeps the total honest.

        Nothing may construct an evaluation whose overall score does not follow
        from its own dimension scores — not a model, not a migration, not a
        future caller taking a shortcut.
        """
        expected = aggregate_score(self.score_map())
        if abs(expected - self.overall_score) > 0.05:
            raise ValueError(
                f"overall_score {self.overall_score} does not follow from the "
                f"dimension scores (expected {expected})"
            )
        return self


def build_evaluation(
    *,
    campaign_id: str,
    generated_asset_id: str,
    specification_id: str,
    specification_version: int,
    scores: dict[Dimension, int],
    strengths: list[str],
    concerns: list[str],
    rationale: str,
    evaluator_model: str | None = None,
    thresholds: DispositionThresholds | None = None,
) -> CreativeEvaluation:
    """The only way an evaluation is made.

    Dimension scores come from the evaluator; the total and the disposition are
    computed here. A caller cannot supply either, which is what makes every
    stored evaluation reproducible from its own numbers.
    """
    overall = aggregate_score(scores)
    disposition, reasons = decide_disposition(scores, overall, thresholds=thresholds)
    return CreativeEvaluation(
        campaign_id=campaign_id,
        generated_asset_id=generated_asset_id,
        specification_id=specification_id,
        specification_version=specification_version,
        evaluator_model=evaluator_model,
        dimensions=[
            DimensionResult(dimension=dimension, score=score) for dimension, score in scores.items()
        ],
        overall_score=overall,
        disposition=disposition,
        disposition_reasons=reasons,
        strengths=strengths[:4],
        concerns=concerns[:4],
        rationale=rationale,
    )


class RankedAsset(DomainModel):
    """One row of the ranking a user sees."""

    generated_asset_id: Id
    evaluation_id: Id
    rank: int = Field(ge=1)
    overall_score: float
    disposition: Disposition
    #: Why this one sits here, in a sentence. Never a reasoning trace.
    reason: str = Field(default="", max_length=300)
    recommended: bool = False


#: Ordering after the overall score. Deterministic and explicit, because a
#: ranking that depended on row order would change between page loads.
TIE_BREAKERS: tuple[Dimension, ...] = (
    Dimension.BRAND_ALIGNMENT,
    Dimension.CAMPAIGN_OBJECTIVE_FIT,
)


def rank_key(evaluation: CreativeEvaluation) -> tuple[float, int, int, str]:
    """The total ordering. Descending score, then the tie-breakers, then id.

    The trailing id is what makes the order *total*: two assets identical on
    every score still have one stable sequence, so the same evaluations always
    render the same ranking.
    """
    return (
        -evaluation.overall_score,
        -evaluation.score_for(TIE_BREAKERS[0]),
        -evaluation.score_for(TIE_BREAKERS[1]),
        evaluation.generated_asset_id,
    )


class Recommendation(DomainModel):
    """What the system suggests, and why. A human still decides."""

    #: None when nothing is recommendable — every asset was rejected.
    generated_asset_id: Id | None = None
    rank: int | None = None
    overall_score: float | None = None
    #: One sentence. "Best balance of brand alignment and campaign relevance."
    reason: str = ""
    #: Said out loud when the best available asset is not actually good.
    caveat: str | None = None


class EvaluationSummary(DomainModel):
    """A campaign's evaluation state, as the UI reads it."""

    campaign_id: Id
    evaluator_version: str = EVALUATOR_VERSION
    ranked: list[RankedAsset] = Field(default_factory=list)
    recommendation: Recommendation | None = None
    #: Assets whose evaluation failed. Named, so a partial batch is legible.
    failed_asset_ids: list[Id] = Field(default_factory=list)
    selected_asset_id: Id | None = None

    def outcome(self) -> str:
        total = len(self.ranked) + len(self.failed_asset_ids)
        if not total:
            return "Nothing evaluated yet."
        if self.failed_asset_ids:
            failed = len(self.failed_asset_ids)
            return f"{len(self.ranked)}/{total} assets evaluated — {failed} failed."
        noun = "asset" if total == 1 else "assets"
        return f"All {total} {noun} evaluated."
