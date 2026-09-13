"""The Brand Guardian service.

Judges one generated plate against the brand's own rules and returns a verdict
that can be argued with.

**Code checks facts; the model judges pictures.** Whether a prohibited claim
appears in the plan, whether the plate carries the constraints that keep it
compositable, whether the palette sits near the brand's colours — all decided
here, deterministically, from data the backend already holds. A model is asked
only what a model can answer: does this *look* like this brand's work.

**The model never returns a verdict.** It reports observations, check by check.
`decide_verdict` turns those plus the deterministic findings into PASS,
NEEDS_REVISION or REJECT. A guardian whose verdict did not follow from its own
findings would be an opinion with a rubber stamp.

**The guardian never invents a rule.** Every check maps to something the Brand
Brain actually defines. A brand that states no colour rules gets
`NOT_APPLICABLE`, not an improvised standard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import Field

from app.domain.campaign import CampaignBrief
from app.domain.common import DomainModel
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.generation import AssetKind, GeneratedAsset
from app.domain.guardian import (
    CHECK_GUIDANCE,
    GUARDIAN_VERSION,
    QUALITATIVE_CHECKS,
    BrandGuardianResult,
    CheckStatus,
    GuardianCheck,
    GuardianCheckResult,
    Severity,
    build_guardian_result,
)
from app.logging import get_logger
from app.providers.base import ImageRef, LLMProvider, ProviderInvalidResponse

log = get_logger(__name__)

#: How far a plate colour may sit from the nearest brand colour before it is
#: worth mentioning. Euclidean distance in RGB, 0-441. Generous on purpose: a
#: guardian that flagged every accent would be noise, and a warning it issues
#: has to be worth reading.
COLOR_DISTANCE_LIMIT = 190.0

GUARDIAN_SYSTEM = (
    "You are a brand guardian reviewing a generated advertising plate. You are "
    "not judging whether it is good — that is someone else's job. You are "
    "judging whether it is acceptable for THIS brand, against the rules the "
    "brand has actually stated. "
    "Report each check as PASS, WARN or FAIL with one short sentence, and a "
    "concrete fix when it does not pass. "
    "Do not return an overall verdict — that is calculated. "
    "Never invent a legal, regulatory or compliance requirement the brand has "
    "not stated. Never include reasoning traces."
)


class ProposedCheck(DomainModel):
    """One qualitative observation as the model returns it."""

    check: GuardianCheck
    status: CheckStatus
    severity: Severity | None = None
    detail: str = Field(default="", max_length=400)
    suggested_fix: str | None = Field(default=None, max_length=300)


class ProposedGuardianReview(DomainModel):
    """The model's output. Validated, never trusted raw.

    Carries no verdict: there is nothing here for a model to rubber-stamp.
    """

    checks: list[ProposedCheck] = Field(min_length=1, max_length=8)
    summary: str = Field(default="", max_length=600)


@dataclass(frozen=True)
class GuardianContext:
    """Everything needed to judge one asset, from scope-checked rows only."""

    asset: GeneratedAsset
    specification: CreativeSpecification
    campaign: CampaignBrief | None = None
    guardrails: BrandGuardrails = field(default_factory=BrandGuardrails)
    brand_name: str | None = None
    #: What the evaluator already found. Used as context, never as a verdict.
    evaluation_concerns: list[str] = field(default_factory=list)


class AssetNotCheckable(ValueError):
    """A deterministic pre-check failed. Never sent to a model."""


def check_checkable(asset: GeneratedAsset) -> None:
    """Facts code settles before spending a model call."""
    if asset.kind is not AssetKind.VISUAL_PLATE:
        raise AssetNotCheckable(
            f"Only visual plates are brand-checked; this asset is {asset.kind.value}."
        )
    if min(asset.width, asset.height) < 256:
        raise AssetNotCheckable(f"The image is too small to assess ({asset.width}x{asset.height}).")


# --------------------------------------------------------------------------
# Deterministic checks
# --------------------------------------------------------------------------
def deterministic_checks(context: GuardianContext) -> list[GuardianCheckResult]:
    """The checks that need no model.

    Each one is a fact about the plan or the asset, decided from the Brand
    Brain. Asking a model to confirm any of these would be slower, less
    reliable, and billable.
    """
    return [
        _claim_check(context),
        _restriction_check(context),
        _color_check(context),
    ]


def _claim_check(context: GuardianContext) -> GuardianCheckResult:
    """A prohibited claim that reached the approved plan.

    Blocking: a creative that carries a claim the brand forbids is not a taste
    problem, and no amount of visual quality redeems it.
    """
    prohibited = context.guardrails.prohibited_claims
    if not prohibited:
        return GuardianCheckResult(
            check=GuardianCheck.CLAIM_SAFETY,
            status=CheckStatus.NOT_APPLICABLE,
            detail="The brand lists no prohibited claims.",
            deterministic=True,
        )

    haystack = _specification_text(context.specification).lower()
    hits = [claim for claim in prohibited if claim.lower() in haystack]
    if hits:
        return GuardianCheckResult(
            check=GuardianCheck.CLAIM_SAFETY,
            status=CheckStatus.FAIL,
            severity=Severity.BLOCKING,
            detail=f"The plan states a prohibited claim: {', '.join(hits)}.",
            suggested_fix=f"Remove any suggestion of: {', '.join(hits)}.",
            deterministic=True,
        )
    return GuardianCheckResult(
        check=GuardianCheck.CLAIM_SAFETY,
        status=CheckStatus.PASS,
        detail="No prohibited claim appears in the approved plan.",
        deterministic=True,
    )


def _restriction_check(context: GuardianContext) -> GuardianCheckResult:
    """The constraints that keep a plate usable.

    `no_text_in_image` is the one that matters: a plate carrying its own
    lettering cannot take the brand's typography later (ADR-006), so a plan
    that switched it off has broken the pipeline rather than bent a rule.
    """
    constraints = context.specification.negative_constraints
    if not constraints.no_text_in_image:
        return GuardianCheckResult(
            check=GuardianCheck.BRAND_RESTRICTIONS,
            status=CheckStatus.FAIL,
            severity=Severity.BLOCKING,
            detail=(
                "The plan allows text in the image. Brand type is applied by the "
                "layout renderer, so a plate with its own lettering cannot be used."
            ),
            suggested_fix="Restore the no-text-in-image constraint.",
            deterministic=True,
        )

    donts = context.guardrails.visual_donts
    if not donts:
        return GuardianCheckResult(
            check=GuardianCheck.BRAND_RESTRICTIONS,
            status=CheckStatus.PASS,
            detail="No stated visual restriction is contradicted by the plan.",
            deterministic=True,
        )

    forbidden = {item.lower() for item in constraints.forbidden_elements}
    missing = [dont for dont in donts if dont.lower() not in forbidden]
    if missing:
        return GuardianCheckResult(
            check=GuardianCheck.BRAND_RESTRICTIONS,
            status=CheckStatus.WARN,
            severity=Severity.MINOR,
            detail=f"{len(missing)} brand restriction(s) were not carried into the plan.",
            suggested_fix=f"Add to the constraints: {'; '.join(missing[:3])}.",
            deterministic=True,
        )
    return GuardianCheckResult(
        check=GuardianCheck.BRAND_RESTRICTIONS,
        status=CheckStatus.PASS,
        detail="Every stated brand restriction is carried into the plan.",
        deterministic=True,
    )


def _color_check(context: GuardianContext) -> GuardianCheckResult:
    """The palette, where it is mechanically checkable.

    A warning rather than a failure: a plate is a background, the exact brand
    colours are applied by the renderer, and an accent outside the palette is
    often a deliberate creative choice. Worth saying; not worth blocking.
    """
    brand_palette = [c for c in context.guardrails.palette if _rgb(c)]
    plate_palette = [c for c in context.specification.palette if _rgb(c)]
    if not brand_palette or not plate_palette:
        return GuardianCheckResult(
            check=GuardianCheck.COLOR_CONSTRAINTS,
            status=CheckStatus.NOT_APPLICABLE,
            detail="No comparable palette is defined.",
            deterministic=True,
        )

    strays = [
        colour
        for colour in plate_palette
        if min(_distance(colour, brand) for brand in brand_palette) > COLOR_DISTANCE_LIMIT
    ]
    if strays:
        return GuardianCheckResult(
            check=GuardianCheck.COLOR_CONSTRAINTS,
            status=CheckStatus.WARN,
            severity=Severity.MINOR,
            detail=f"{', '.join(strays)} sit outside the brand palette.",
            suggested_fix="Pull the accent closer to a brand colour, or confirm it is intended.",
            deterministic=True,
        )
    return GuardianCheckResult(
        check=GuardianCheck.COLOR_CONSTRAINTS,
        status=CheckStatus.PASS,
        detail="The palette sits within the brand's colour world.",
        deterministic=True,
    )


def _specification_text(specification: CreativeSpecification) -> str:
    """The prose a claim could hide in."""
    return " ".join(
        str(value)
        for value in (
            specification.concept,
            specification.visual_story,
            specification.headline,
            specification.subhead or "",
            specification.cta,
            specification.body_copy or "",
            specification.product_integration,
            specification.brand_integration,
            specification.visual_metaphor,
        )
    )


def _rgb(hex_colour: str) -> tuple[int, int, int] | None:
    value = hex_colour.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return None
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return None


def _distance(first: str, second: str) -> float:
    a, b = _rgb(first), _rgb(second)
    if a is None or b is None:
        return 0.0
    return float(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5)


# --------------------------------------------------------------------------
# The service
# --------------------------------------------------------------------------
def build_guardian_prompt(context: GuardianContext) -> str:
    """The brief. Brand rules first, then what each check means."""
    specification = context.specification
    guardrails = context.guardrails
    lines: list[str] = [
        "Review the attached generated image against this brand's stated rules.",
        "",
        f"BRAND: {context.brand_name or 'this brand'}",
    ]
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
    if guardrails.approved_claims:
        lines.append(f"APPROVED CLAIMS: {'; '.join(guardrails.approved_claims)}")
    if guardrails.logo_rules:
        lines.append(f"LOGO RULES: {'; '.join(guardrails.logo_rules)}")

    lines += [
        "",
        f"APPROVED PLAN (Creative Specification v{specification.version}):",
        f"SUBJECT: {specification.subject}",
        f"ENVIRONMENT: {specification.environment}",
        f"PRODUCT INTEGRATION: {specification.product_integration}",
        f"BRAND INTEGRATION: {specification.brand_integration}",
    ]
    if context.campaign is not None:
        lines += [
            "",
            f"PRODUCT: {context.campaign.product}",
            f"AUDIENCE: {context.campaign.audience}",
        ]
    if context.evaluation_concerns:
        lines += [
            "",
            "THE CREATIVE REVIEW ALREADY NOTED: " + "; ".join(context.evaluation_concerns[:3]),
            "Use that as context. Judge brand acceptability, not creative quality.",
        ]

    lines += ["", "REPORT ON EACH OF THESE:"]
    lines += [f"{check.value}: {CHECK_GUIDANCE[check]}" for check in QUALITATIVE_CHECKS]
    lines += [
        "",
        "This image is a VISUAL PLATE: the logo, headline, call to action and exact "
        "brand colours are composited afterwards by a deterministic renderer. Judge "
        "whether the plate is acceptable *as a background for that*, and treat any "
        "text or logo already rendered in the image as a failure.",
    ]
    return "\n".join(lines)


class BrandGuardian:
    """One asset in, one validated verdict out."""

    version = GUARDIAN_VERSION

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def review(self, context: GuardianContext, image: ImageRef) -> BrandGuardianResult:
        """Check one plate.

        Raises `AssetNotCheckable` when a deterministic pre-check fails, and
        `ProviderError` when the model call does — both recorded by the caller
        as an explicit failure rather than a silently missing verdict.
        """
        check_checkable(context.asset)

        proposed = await self.llm.structured(
            build_guardian_prompt(context),
            ProposedGuardianReview,
            system=GUARDIAN_SYSTEM,
            images=(image,),
        )

        # Code wins where both have an opinion: a deterministic finding is a
        # fact about the data, and a model's impression of the same thing is
        # not evidence against it.
        checks = deterministic_checks(context)
        settled = {result.check for result in checks}
        for item in proposed.checks:
            if item.check in settled:
                continue
            checks.append(
                GuardianCheckResult(
                    check=item.check,
                    status=item.status,
                    severity=item.severity or _default_severity(item.status),
                    detail=item.detail or _default_detail(item),
                    suggested_fix=item.suggested_fix,
                    deterministic=False,
                )
            )

        if not checks:
            raise ProviderInvalidResponse(
                "The brand check produced no findings.", provider=self.llm.name
            )

        result = build_guardian_result(
            campaign_id=context.asset.campaign_id,
            generated_asset_id=context.asset.id,
            specification_id=context.asset.specification_id,
            specification_version=context.asset.specification_version,
            checks=checks,
            summary=proposed.summary,
            guardian_model=getattr(self.llm, "name", None),
        )
        log.info(
            "asset_brand_checked",
            asset_id=context.asset.id,
            verdict=result.verdict.value,
            guardian_version=self.version,
        )
        return result


def _default_severity(status: CheckStatus) -> Severity | None:
    """A model that reported a failure without a severity still has to produce
    a valid finding, so one is supplied rather than discarding the check."""
    if status is CheckStatus.FAIL:
        return Severity.MAJOR
    if status is CheckStatus.WARN:
        return Severity.MINOR
    return None


def _default_detail(item: ProposedCheck) -> str:
    if item.status in (CheckStatus.FAIL, CheckStatus.WARN):
        return f"{item.check.value.replace('_', ' ')} did not meet the brand's rules."
    return ""
