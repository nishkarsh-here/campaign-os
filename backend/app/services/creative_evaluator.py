"""The Creative Evaluator.

Judges one generated plate against the plan it was generated from, and answers
the only question that matters once several creatives exist: *which of these is
right for this campaign?*

Three boundaries hold this together.

**It assesses; it never creates.** The evaluator may say keep, revise or reject,
and it may say why. It never rewrites a prompt or a specification — a revision
is Milestone 8's job, and an evaluator that quietly edits its subject is no
longer an evaluator.

**The model judges; this module decides.** The model returns dimension scores
and short notes, and nothing else. The overall score and the disposition are
computed from those numbers by `app.domain.evaluation`, so a verdict is always
reproducible and always arguable. Asking a model for a total produces one that
does not follow from its own scores.

**The backend never asks the model what it already knows.** Whether the asset
exists, which campaign it belongs to, its dimensions, its MIME type, which
specification version produced it — all of that is checked here in code. The
model is asked only for qualitative visual judgement, which is the one thing
code cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field

from app.domain.campaign import CampaignBrief
from app.domain.common import DomainModel
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.evaluation import (
    DIMENSION_GUIDANCE,
    EVALUATOR_VERSION,
    CreativeEvaluation,
    Dimension,
    DimensionScore,
    DispositionThresholds,
    build_evaluation,
)
from app.domain.generation import AssetKind, GeneratedAsset
from app.domain.reference import AggregateReferenceStyle
from app.logging import get_logger
from app.providers.base import ImageRef, LLMProvider, ProviderInvalidResponse

log = get_logger(__name__)

#: The smallest plate worth judging. Below this the image is a thumbnail or a
#: truncated download, and a visual score would be meaningless.
MIN_PLATE_EDGE = 256

#: What the evaluator will look at. A plate is always a raster image.
EVALUABLE_MIME_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp"})

EVALUATOR_SYSTEM = (
    "You are a senior creative director reviewing a generated advertising plate "
    "against an approved campaign plan. You assess fitness for purpose, not "
    "prettiness: a beautiful image that misses the objective scores badly. "
    "Score each dimension from 0 to 100 and give one short sentence for each. "
    "Do not return an overall score or a verdict — those are calculated. "
    "Do not suggest rewritten prompts or specifications. "
    "Never include reasoning traces; every note must be a single readable line."
)


class ProposedDimension(DomainModel):
    """One dimension as the model returns it."""

    dimension: Dimension
    score: DimensionScore
    note: str = Field(default="", max_length=300)


class ProposedEvaluation(DomainModel):
    """The model's output. Validated, never trusted raw.

    Deliberately carries no overall score and no disposition: both are computed
    from the dimensions, so there is nothing here for a model to invent.
    """

    dimensions: list[ProposedDimension] = Field(min_length=1, max_length=10)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    concerns: list[str] = Field(default_factory=list, max_length=6)
    rationale: str = Field(default="", max_length=600)


@dataclass(frozen=True)
class EvaluationContext:
    """Everything needed to judge one asset.

    Assembled by the caller from scope-checked rows. The `specification` is
    always the one the *asset* was generated from — never a later approved
    revision, or the evaluation would be marking the work against a plan it was
    never given.
    """

    asset: GeneratedAsset
    specification: CreativeSpecification
    campaign: CampaignBrief | None = None
    guardrails: BrandGuardrails = field(default_factory=BrandGuardrails)
    reference_style: AggregateReferenceStyle = field(default_factory=AggregateReferenceStyle)
    brand_name: str | None = None


class AssetNotEvaluable(ValueError):
    """A deterministic pre-check failed. Never sent to a model."""


def check_evaluable(asset: GeneratedAsset) -> None:
    """The facts code can settle without spending a model call.

    Everything here is knowable from the row. Asking a model to confirm an
    image's MIME type would be slower, less reliable and billable.
    """
    if asset.kind is not AssetKind.VISUAL_PLATE:
        raise AssetNotEvaluable(
            f"Only visual plates are evaluated; this asset is {asset.kind.value}."
        )
    if asset.mime_type not in EVALUABLE_MIME_TYPES:
        raise AssetNotEvaluable(f"{asset.mime_type} is not an evaluable image type.")
    if min(asset.width, asset.height) < MIN_PLATE_EDGE:
        raise AssetNotEvaluable(f"The image is too small to assess ({asset.width}x{asset.height}).")


def build_evaluation_prompt(context: EvaluationContext) -> str:
    """The judgement brief.

    Structured facts first, then what each dimension means. The model is given
    the plan and the picture and asked to compare them — it is never asked to
    recall or re-derive anything the backend already holds.
    """
    specification = context.specification
    lines: list[str] = [
        "Assess the attached generated image against this approved plan.",
        "",
        f"APPROVED CREATIVE SPECIFICATION (version {specification.version}):",
        f"CONCEPT: {specification.concept}",
        f"EMOTIONAL ANGLE: {specification.emotional_angle}",
        f"SUBJECT: {specification.subject}",
        f"ENVIRONMENT: {specification.environment}",
        f"COMPOSITION: {specification.composition}",
        f"LIGHTING: {specification.lighting}",
        f"PRODUCT INTEGRATION: {specification.product_integration}",
        f"BRAND INTEGRATION: {specification.brand_integration}",
    ]
    if specification.focal_point:
        lines.append(f"FOCAL POINT: {specification.focal_point}")
    if specification.color_direction:
        lines.append(f"COLOUR DIRECTION: {specification.color_direction}")
    if specification.people_guidance:
        lines.append(f"PEOPLE: {specification.people_guidance}")
    if specification.style_families:
        lines.append("INTENDED STYLE: " + ", ".join(s.value for s in specification.style_families))
    if specification.mood:
        lines.append(f"INTENDED MOOD: {', '.join(specification.mood)}")

    if context.campaign is not None:
        campaign = context.campaign
        lines += [
            "",
            "CAMPAIGN SPECIFICATION:",
            f"OBJECTIVE: {campaign.objective}",
            f"AUDIENCE: {campaign.audience}",
            f"PRODUCT: {campaign.product}",
            f"KEY MESSAGE: {campaign.key_message}",
        ]
        if campaign.region:
            lines.append(f"REGION: {campaign.region}")
        else:
            lines.append("REGION: not specified — score regional fit 50.")

    guardrails = context.guardrails
    if context.brand_name or guardrails.tone_attributes or guardrails.prohibited_claims:
        lines += ["", "BRAND:"]
        if context.brand_name:
            lines.append(f"NAME: {context.brand_name}")
        if guardrails.tone_attributes:
            lines.append(f"TONE: {', '.join(guardrails.tone_attributes)}")
        if guardrails.palette:
            lines.append(f"BRAND COLOURS: {', '.join(guardrails.palette)}")
        if guardrails.visual_dos:
            lines.append(f"VISUAL DOS: {'; '.join(guardrails.visual_dos)}")
        if guardrails.visual_donts:
            lines.append(f"VISUAL DONTS: {'; '.join(guardrails.visual_donts)}")
        if guardrails.prohibited_claims:
            lines.append(f"NEVER IMPLY: {'; '.join(guardrails.prohibited_claims)}")

    style = context.reference_style
    if style.reference_count:
        # Abstract characteristics only. What the user liked *about* their
        # references, never the references themselves (ADR-011).
        intended: list[str] = [s.value.replace("_", " ") for s in style.dominant_styles]
        intended += list(style.shared_takeaways[:4])
        if style.common_lighting is not None:
            intended.append(f"{style.common_lighting.value.replace('_', ' ')} light")
        lines += [
            "",
            "INTENDED STYLE CHARACTERISTICS: " + ", ".join(intended),
            "Judge only whether the image achieves these qualities. Never judge "
            "whether it resembles any particular reference image.",
        ]

    lines += ["", "SCORE EACH DIMENSION 0-100:"]
    lines += [f"{dimension.value}: {DIMENSION_GUIDANCE[dimension]}" for dimension in Dimension]
    lines += [
        "",
        "This image is a VISUAL PLATE. The logo, headline, call to action and exact "
        "brand colours are composited afterwards by a deterministic renderer. Judge "
        "it as a background for that, and treat any text already rendered in the "
        "image as a defect.",
    ]
    return "\n".join(lines)


class CreativeEvaluator:
    """One asset in, one validated evaluation out."""

    version = EVALUATOR_VERSION

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def evaluate(
        self,
        context: EvaluationContext,
        image: ImageRef,
        *,
        thresholds: DispositionThresholds | None = None,
    ) -> CreativeEvaluation:
        """Judge one plate.

        Raises `AssetNotEvaluable` when a deterministic pre-check fails, and
        `ProviderError` when the model call does — both recorded by the caller
        as an explicit failure rather than a silently missing evaluation.
        """
        check_evaluable(context.asset)

        proposed = await self.llm.structured(
            build_evaluation_prompt(context),
            ProposedEvaluation,
            system=EVALUATOR_SYSTEM,
            images=(image,),
        )
        scores = {item.dimension: item.score for item in proposed.dimensions}
        if not scores:
            raise ProviderInvalidResponse(
                "The evaluator returned no dimension scores.", provider=self.llm.name
            )

        evaluation = build_evaluation(
            campaign_id=context.asset.campaign_id,
            generated_asset_id=context.asset.id,
            # Provenance: the plan this asset actually came from.
            specification_id=context.asset.specification_id,
            specification_version=context.asset.specification_version,
            scores=scores,
            strengths=list(proposed.strengths),
            concerns=list(proposed.concerns),
            rationale=proposed.rationale,
            evaluator_model=getattr(self.llm, "name", None),
            thresholds=thresholds,
        )
        # Notes are carried back onto the computed result, so every score can
        # be read with its one-line justification.
        notes = {item.dimension: item.note for item in proposed.dimensions}
        for result in evaluation.dimensions:
            result.note = notes.get(result.dimension, "")

        log.info(
            "asset_evaluated",
            asset_id=context.asset.id,
            overall=evaluation.overall_score,
            disposition=evaluation.disposition.value,
            evaluator_version=self.version,
        )
        return evaluation
