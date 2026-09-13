"""The Prompt Compiler.

Turns an approved `CreativeSpecification` into a `CanonicalPrompt` — the
provider-neutral structured form — from which provider adapters render their
own wording.

Three properties matter more than anything else here:

**It is deterministic.** No model call. The approved specification is already
structured, so rearranging it into image controls is a pure function: the same
specification always compiles to the same prompt, which is what makes a prompt
reproducible from its source and a compile free to run as often as it likes.

**It does not mutate its source.** The specification is read, never written.
A provider that wants different wording gets a different `ModelPrompt`, not an
edited plan — the hierarchy is Campaign Specification → Creative Direction →
Creative Specification → Canonical Prompt → Model Prompt → Asset, and it only
ever flows downhill.

**It keeps the brand out of the image model's hands** (ADR-006). Typography
becomes a request to leave an area quiet, never a request to set the headline;
`no_text_in_image` goes into every negative constraint list. The image model
produces a plate. The deterministic renderer applies the brand.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.common import CHANNEL_DIMENSIONS, Channel
from app.domain.creative import CreativeSpecification, NegativeConstraints
from app.domain.creative_context import CreativeContext
from app.domain.prompt import CanonicalPrompt, fingerprint, nearest_aspect_ratio
from app.domain.reference import ReferenceAnalysis
from app.logging import get_logger

log = get_logger(__name__)

#: The specification fields a prompt is compiled from. The fingerprint covers
#: exactly these, so "has the source changed?" has a precise answer.
COMPILED_FROM: tuple[str, ...] = (
    "subject",
    "environment",
    "visual_story",
    "composition",
    "focal_point",
    "camera",
    "lighting",
    "color_direction",
    "palette",
    "mood",
    "style_families",
    "product_integration",
    "people_guidance",
    "brand_integration",
    "regional_cues",
    "typography_guidance",
    "negative_constraints",
)

#: How the plate leaves room for type. Deliberately about *composition*, not
#: about letterforms: the image model is being told where to be quiet.
_TEXT_SAFE_AREA = (
    "an uncluttered area with even tone where a headline and call to action "
    "will be composited later — no lettering of any kind in the image itself"
)


class PromptCompiler:
    """`CreativeSpecification` (+ context) -> `CanonicalPrompt`."""

    def compile(
        self,
        specification: CreativeSpecification,
        *,
        context: CreativeContext | None = None,
        version: int = 1,
    ) -> CanonicalPrompt:
        source = {field: _plain(getattr(specification, field, None)) for field in COMPILED_FROM}
        canonical = CanonicalPrompt(
            campaign_id=specification.campaign_id,
            specification_id=specification.id,
            specification_version=specification.version,
            version=version,
            subject=specification.subject,
            environment=specification.environment,
            visual_story=specification.visual_story,
            composition=specification.composition,
            focal_point=specification.focal_point,
            camera=specification.camera,
            lighting=specification.lighting,
            color_direction=specification.color_direction,
            palette=list(specification.palette),
            mood=list(specification.mood),
            style_families=list(specification.style_families),
            product_integration=specification.product_integration,
            people_guidance=specification.people_guidance,
            brand_integration=specification.brand_integration,
            # Region is carried, never invented: only what the Campaign
            # Specification already established reaches the prompt.
            regional_cues=list(specification.regional_cues),
            typography_guidance=specification.typography_guidance,
            text_safe_area=_TEXT_SAFE_AREA,
            negative_constraints=_negatives(specification, context),
            reference_characteristics=_reference_characteristics(context),
            aspect_ratio=_aspect_ratio(context),
            source_fingerprint=fingerprint(source),
        )
        log.info(
            "prompt_compiled",
            campaign_id=specification.campaign_id,
            specification_version=specification.version,
            version=version,
        )
        return canonical


def _plain(value: object) -> object:
    """A fingerprint-safe rendering of a field. Nested models become their
    dumped form so a change inside one still changes the digest."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _negatives(
    specification: CreativeSpecification, context: CreativeContext | None
) -> NegativeConstraints:
    """The specification's constraints, plus the brand's prohibitions.

    `no_text_in_image` is forced on regardless of what the specification says.
    Brand text in a generated plate is not a stylistic preference — it is the
    wrong renderer doing the job (ADR-006), and no upstream field may switch
    that off.
    """
    base = specification.negative_constraints
    forbidden_text = list(base.forbidden_text)
    forbidden_elements = list(base.forbidden_elements)

    if context is not None:
        for claim in context.guardrails.prohibited_claims:
            if claim not in forbidden_text:
                forbidden_text.append(claim)
        for dont in context.guardrails.visual_donts:
            if dont not in forbidden_elements:
                forbidden_elements.append(dont)

    # The IP boundary, restated as instructions to the image model. These are
    # the same items `ReferenceAnalysis.forbids_reproduction()` names, so
    # widening one widens the other rather than leaving the prompt behind.
    for forbidden in ReferenceAnalysis.forbids_reproduction():
        if forbidden not in forbidden_elements:
            forbidden_elements.append(forbidden)

    return NegativeConstraints(
        forbidden_elements=forbidden_elements,
        forbidden_text=forbidden_text,
        avoid_styles=list(base.avoid_styles),
        no_text_in_image=True,
    )


def _reference_characteristics(context: CreativeContext | None) -> list[str]:
    """Abstract style qualities only.

    `AggregateReferenceStyle` is already the safe surface — it holds no text,
    no logo, no layout coordinates and no font family, because
    `ReferenceAnalysis` has nowhere to put them (ADR-011). Reading it rather
    than the individual analyses is what keeps that true here.
    """
    if context is None:
        return []
    style = context.reference_style
    qualities: list[str] = list(style.shared_takeaways[:4])
    if style.common_lighting is not None:
        qualities.append(f"{style.common_lighting.value.replace('_', ' ')} light")
    if style.common_density is not None:
        qualities.append(f"{style.common_density.value.replace('_', ' ')} visual density")
    return qualities[:8]


#: Ratios every supported image provider accepts. A channel is snapped to the
#: closest one rather than sent a ratio a provider would reject.
SUPPORTED_RATIOS: tuple[str, ...] = ("1:1", "3:4", "4:3", "9:16", "16:9")


def aspect_ratio_for(channel: Channel) -> str:
    """The generation ratio for a channel, derived from `CHANNEL_DIMENSIONS`.

    Derived rather than tabulated: the layout engine already owns each
    channel's exact pixels, and a second hand-written table would be free to
    disagree with it. The plate only needs the closest *shape* — the
    deterministic renderer crops to the exact size later.
    """
    width, height = CHANNEL_DIMENSIONS[channel]
    return nearest_aspect_ratio(f"{width}:{height}", SUPPORTED_RATIOS)


def _aspect_ratio(context: CreativeContext | None) -> str:
    """The first channel's shape, or square.

    One ratio per compile: a prompt targets one frame, and a second channel is
    a second compile rather than a prompt that hedges.
    """
    if context is None or context.specification is None:
        return "1:1"
    for channel in context.specification.channels:
        return aspect_ratio_for(channel)
    return "1:1"
