"""The Creative Director.

Turns a `CreativeContext` — brand, campaign specification, reference style DNA
and preferences, already assembled in Milestone 4 — into three genuinely
different strategic directions.

Two things make this more than "ask a model for three ideas":

**It consumes the context, it does not rebuild it.** No brand rule is
re-derived and no preference re-weighted here; that separation is what stops
brand logic being copied into every future node.

**Distinctness is checked, not hoped for.** Three variations on one poster is
the common failure of this feature, so `assess_diversity` compares the
structured *choices* — angle, subject, environment, composition, lighting,
style — and a set that collides is regenerated with explicit instructions to
diverge. Deterministic set overlap, not clustering: the question does not need
a model, and a model would make the answer unrepeatable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from app.domain.common import DomainModel, StyleFamily
from app.domain.creative import (
    PROTECTED_CAMPAIGN_FACTS,
    CreativeDirection,
    CreativeDirectionSet,
    CreativeRevisionDelta,
    CreativeSpecification,
    DiversityVerdict,
    NegativeConstraints,
    TypographyGuidance,
)
from app.domain.creative_context import CreativeContext
from app.logging import get_logger
from app.providers.base import LLMProvider

log = get_logger(__name__)

DIRECTION_COUNT = 3
#: Above this Jaccard overlap two directions are the same idea reworded.
SIMILARITY_LIMIT = 0.55
#: One retry. A model that cannot diverge twice will not diverge on the third.
MAX_DIVERSITY_RETRIES = 1

DIRECTOR_SYSTEM = (
    "You are a creative director. You produce distinct strategic directions for "
    "a campaign — different ideas, not variations of one idea. Each must take a "
    "different emotional angle and show a different scene. "
    "Never reproduce a reference's text, logo, typeface or layout; you may only "
    "carry forward abstract qualities such as lighting, density and composition. "
    "Never invent regional or factual claims the brief does not contain."
)

SPECIFICATION_SYSTEM = (
    "You turn an approved creative direction into a precise execution plan for "
    "an art director. Be concrete about subject, setting, framing and light. "
    "Never specify a font family, never reproduce reference content, and never "
    "add a claim the brief does not support."
)


class ProposedDirection(DomainModel):
    """One direction as the model returns it. Validated, never trusted raw."""

    title: str = Field(min_length=2, max_length=120)
    big_idea: str = Field(min_length=5, max_length=400)
    strategic_rationale: str = Field(min_length=5, max_length=800)
    emotional_angle: str = Field(min_length=3, max_length=200)
    audience_connection: str = Field(default="", max_length=500)
    key_message: str = Field(default="", max_length=400)
    headline: str = Field(min_length=2, max_length=200)
    subhead: str | None = Field(default=None, max_length=300)
    cta: str = Field(min_length=1, max_length=120)
    cta_direction: str = Field(default="", max_length=300)
    visual_metaphor: str = Field(min_length=3, max_length=400)
    composition: str = Field(min_length=3, max_length=400)
    subject: str = Field(min_length=3, max_length=400)
    environment: str = Field(min_length=3, max_length=400)
    lighting: str = Field(min_length=3, max_length=300)
    palette: list[str] = Field(default_factory=list, max_length=8)
    color_direction: str = Field(default="", max_length=300)
    style_families: list[StyleFamily] = Field(default_factory=list, max_length=4)
    brand_integration: str = Field(default="", max_length=500)
    product_integration: str = Field(default="", max_length=500)
    regional_considerations: list[str] = Field(default_factory=list, max_length=6)
    reference_characteristics_used: list[str] = Field(default_factory=list, max_length=6)
    reference_characteristics_avoided: list[str] = Field(default_factory=list, max_length=6)
    distinctness_note: str | None = Field(default=None, max_length=300)


class ProposedDirectionSet(DomainModel):
    """The model's three options plus its recommendation."""

    directions: list[ProposedDirection] = Field(min_length=1, max_length=5)
    recommended_index: int = Field(default=0, ge=0, le=4)
    recommendation_reasons: list[str] = Field(default_factory=list, max_length=6)


class ProposedSpecification(DomainModel):
    """The execution plan as the model returns it."""

    concept: str = Field(min_length=5, max_length=800)
    visual_story: str = Field(default="", max_length=1200)
    emotional_angle: str = Field(min_length=3, max_length=200)
    headline: str = Field(min_length=2, max_length=200)
    headline_guidance: str = Field(default="", max_length=400)
    subhead: str | None = Field(default=None, max_length=300)
    cta: str = Field(min_length=1, max_length=120)
    cta_guidance: str = Field(default="", max_length=400)
    visual_metaphor: str = Field(min_length=3, max_length=400)
    composition: str = Field(min_length=3, max_length=500)
    focal_point: str = Field(default="", max_length=300)
    subject: str = Field(min_length=3, max_length=500)
    environment: str = Field(min_length=3, max_length=500)
    lighting: str = Field(min_length=3, max_length=400)
    camera: str | None = Field(default=None, max_length=200)
    palette: list[str] = Field(default_factory=list, max_length=8)
    color_direction: str = Field(default="", max_length=400)
    mood: list[str] = Field(default_factory=list, max_length=6)
    product_integration: str = Field(default="", max_length=500)
    people_guidance: str = Field(default="", max_length=400)
    brand_integration: str = Field(default="", max_length=500)
    regional_cues: list[str] = Field(default_factory=list, max_length=6)


@dataclass(frozen=True)
class DirectionOutcome:
    """What a generation attempt produced, and whether it was distinct enough."""

    direction_set: CreativeDirectionSet
    diversity: DiversityVerdict
    attempts: int


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap. 1.0 is identical, 0.0 shares nothing."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def assess_diversity(
    directions: list[CreativeDirection], *, limit: float = SIMILARITY_LIMIT
) -> DiversityVerdict:
    """Are these three ideas, or one idea three times?

    Compares structured choices rather than prose — two directions can be
    worded very differently and still put the same subject in the same place
    under the same light.
    """
    collisions: list[tuple[int, int, float]] = []
    worst = 0.0
    for i, first in enumerate(directions):
        for second in directions[i + 1 :]:
            score = _similarity(first.diversity_signature(), second.diversity_signature())
            worst = max(worst, score)
            if score > limit:
                collisions.append((first.ordinal, second.ordinal, round(score, 3)))
    return DiversityVerdict(
        passed=not collisions,
        collisions=collisions,
        weakest_pair_similarity=round(worst, 3),
    )


def build_director_prompt(
    context: CreativeContext,
    *,
    revision: CreativeRevisionDelta | None = None,
    diversity_retry: DiversityVerdict | None = None,
) -> str:
    """Everything the director needs, drawn from the assembled context."""
    spec = context.specification
    lines: list[str] = [f"CAMPAIGN: {spec.title if spec else 'untitled'}"]
    if spec is not None:
        lines += [
            f"OBJECTIVE: {spec.objective}",
            f"AUDIENCE: {spec.audience}",
            f"PRODUCT: {spec.product}",
            f"KEY MESSAGE: {spec.key_message}",
            f"CALL TO ACTION: {spec.cta}",
            f"CHANNELS: {', '.join(c.value for c in spec.channels)}",
        ]
        if spec.region:
            lines.append(f"REGION: {spec.region}")
        if spec.desired_emotional_response:
            lines.append(f"DESIRED FEELING: {spec.desired_emotional_response}")
        if spec.constraints:
            lines.append(f"CONSTRAINTS: {'; '.join(spec.constraints)}")

    guardrails = context.guardrails
    if context.brand_name:
        lines.append(f"BRAND: {context.brand_name}")
    if guardrails.tone_attributes:
        lines.append(f"BRAND TONE: {', '.join(guardrails.tone_attributes)}")
    if guardrails.palette:
        lines.append(f"BRAND COLOURS: {', '.join(guardrails.palette)}")
    if guardrails.prohibited_claims:
        lines.append(f"NEVER CLAIM: {'; '.join(guardrails.prohibited_claims)}")
    if guardrails.visual_donts:
        lines.append(f"VISUAL DON'TS: {'; '.join(guardrails.visual_donts)}")

    style = context.reference_style
    if style.reference_count:
        observed = [
            (
                f"styles: {', '.join(s.value for s in style.dominant_styles)}"
                if style.dominant_styles
                else ""
            ),
            f"composition: {style.common_composition.value}" if style.common_composition else "",
            f"lighting: {style.common_lighting.value}" if style.common_lighting else "",
            f"density: {style.common_density.value}" if style.common_density else "",
        ]
        lines.append(
            "REFERENCE STYLE (abstract qualities only): " + "; ".join(x for x in observed if x)
        )
        if style.tensions:
            lines.append(f"REFERENCES DISAGREE ON: {'; '.join(style.tensions)}")
    if context.style_profile.weights:
        lines.append(f"VISUAL PREFERENCE: {context.style_profile.describe()}")

    lines.append(
        "Produce THREE directions that differ in strategic and emotional angle — "
        "not three versions of one scene. Draw the angles from this campaign and "
        "brand, not from a fixed list."
    )
    lines.append(
        "For each, state which abstract reference characteristics you are "
        "carrying forward and which you are deliberately leaving behind."
    )
    if context.gaps:
        # Naming the gaps stops the model inventing facts to fill them.
        lines.append("NOT ESTABLISHED — do not invent these: " + "; ".join(context.gaps))

    if revision is not None:
        lines.append(
            "REVISION REQUESTED: "
            f"{revision.feedback}\n"
            f"KEEP UNCHANGED: {', '.join(revision.keep) or 'the campaign facts'}\n"
            f"CHANGE: {', '.join(revision.change) or 'the creative angle'}"
        )
    if diversity_retry is not None:
        lines.append(
            "YOUR PREVIOUS ATTEMPT WAS TOO REPETITIVE: "
            f"{diversity_retry.describe()} "
            "Change the subject, the setting and the emotional angle between them."
        )
    return "\n\n".join(lines)


def build_specification_prompt(
    context: CreativeContext,
    direction: CreativeDirection,
    *,
    preserve: list[str] | None = None,
) -> str:
    lines = [
        f"APPROVED DIRECTION: {direction.title}",
        f"CONCEPT: {direction.big_idea}",
        f"EMOTIONAL ANGLE: {direction.emotional_angle}",
        f"HEADLINE: {direction.headline}",
        f"SUBJECT: {direction.subject}",
        f"ENVIRONMENT: {direction.environment}",
        f"COMPOSITION: {direction.composition}",
        f"LIGHTING: {direction.lighting}",
        f"PRODUCT: {direction.product_integration}",
        f"BRAND: {direction.brand_integration}",
        # Protected campaign facts. They are pinned after generation too — this
        # is here so a model is not asked to invent what it must reproduce.
        f"KEY MESSAGE: {direction.key_message}",
        f"CALL TO ACTION: {direction.cta}",
    ]
    if context.specification is not None:
        lines.append(f"CAMPAIGN OBJECTIVE: {context.specification.objective}")
        lines.append(f"AUDIENCE: {context.specification.audience}")
    if context.guardrails.prohibited_claims:
        lines.append(f"NEVER CLAIM: {'; '.join(context.guardrails.prohibited_claims)}")
    lines.append(
        "Write the execution plan. Do not name a font family and do not "
        "reproduce any reference's text, logo or layout."
    )
    if preserve:
        lines.append(
            "A HUMAN HAS EDITED THESE FIELDS — reproduce them exactly as given: "
            + ", ".join(preserve)
        )
    return "\n\n".join(lines)


class CreativeDirector:
    """Generates directions and, once one is chosen, its execution plan."""

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def propose_directions(
        self,
        context: CreativeContext,
        *,
        version: int = 1,
        revision: CreativeRevisionDelta | None = None,
    ) -> DirectionOutcome:
        """Three directions, checked for distinctness and retried once if not.

        Raises `ProviderError` on malformed output — a failure the caller
        records as a typed execution error rather than silently accepting.
        """
        retry_hint: DiversityVerdict | None = None
        outcome: DirectionOutcome | None = None

        for attempt in range(MAX_DIVERSITY_RETRIES + 1):
            proposed = await self.llm.structured(
                build_director_prompt(context, revision=revision, diversity_retry=retry_hint),
                ProposedDirectionSet,
                system=DIRECTOR_SYSTEM,
            )
            directions = [
                _to_direction(p, context, ordinal=i + 1)
                for i, p in enumerate(proposed.directions[:DIRECTION_COUNT])
            ]
            verdict = assess_diversity(directions)
            recommended = min(proposed.recommended_index, len(directions) - 1) + 1
            outcome = DirectionOutcome(
                direction_set=CreativeDirectionSet(
                    campaign_id=context.campaign_id,
                    version=version,
                    directions=directions,
                    recommended_ordinal=recommended,
                    recommendation_reasons=proposed.recommendation_reasons
                    or _default_reasons(context, directions[recommended - 1]),
                    diversity=verdict,
                    revision_of_version=version - 1 if revision else None,
                ),
                diversity=verdict,
                attempts=attempt + 1,
            )
            if verdict.passed:
                return outcome
            log.info(
                "creative_directions_too_similar",
                attempt=attempt + 1,
                similarity=verdict.weakest_pair_similarity,
            )
            retry_hint = verdict

        # Exhausted the retry. Return the set with its verdict attached rather
        # than pretending it passed — the UI shows the warning and the human
        # can ask for a revision.
        assert outcome is not None
        return outcome

    async def build_specification(
        self,
        context: CreativeContext,
        direction: CreativeDirection,
        *,
        version: int = 1,
        previous: CreativeSpecification | None = None,
    ) -> CreativeSpecification:
        """The execution plan for the chosen direction.

        Fields a human edited on a previous version are carried forward
        untouched — a regeneration must never quietly undo an edit.
        """
        preserved = list(previous.human_edited_fields) if previous else []
        proposed = await self.llm.structured(
            build_specification_prompt(context, direction, preserve=preserved),
            ProposedSpecification,
            system=SPECIFICATION_SYSTEM,
        )

        data = proposed.model_dump()
        # Pinned again here: the specification is generated by a second model
        # call, which is a second chance to drift off the confirmed facts.
        data.update(_pinned_facts(context, CreativeSpecification))
        for field in preserved:
            if previous is not None and field in CreativeSpecification.model_fields:
                data[field] = getattr(previous, field)

        return CreativeSpecification(
            campaign_id=context.campaign_id,
            direction_id=direction.id,
            version=version,
            style_families=list(direction.style_families),
            typography_guidance=(
                previous.typography_guidance if previous else _default_typography()
            ),
            negative_constraints=_negative_constraints(
                context, direction.reference_characteristics_avoided
            ),
            human_edited_fields=preserved,
            **data,
        )


def _default_typography() -> TypographyGuidance:
    """Guidance the compositor can act on, stated as weight, case and scale.

    Never a typeface: the brand's own font is applied by the deterministic
    composition step (ADR-006), and naming one taken from a reference would
    cross the style/copy boundary (ADR-011).
    """
    return TypographyGuidance(
        headline_treatment="Large, tight leading, sentence case; weight carries the emphasis.",
        hierarchy="Headline, then CTA, then any supporting line — never three equal weights.",
    )


def _negative_constraints(context: CreativeContext, avoided: list[str]) -> NegativeConstraints:
    """What must not appear.

    Brand prohibitions plus the reference characteristics this direction is
    deliberately leaving behind. `no_text_in_image` stays true: brand text is
    composed deterministically afterwards (ADR-006).
    """
    return NegativeConstraints(
        forbidden_elements=list(dict.fromkeys([*context.guardrails.visual_donts, *avoided]))[:12],
        forbidden_text=list(context.guardrails.prohibited_claims)[:12],
        avoid_styles=list(context.preferences.avoid)[:8],
        no_text_in_image=True,
    )


def _to_direction(
    proposed: ProposedDirection, context: CreativeContext, *, ordinal: int
) -> CreativeDirection:
    """The model's proposal, with the confirmed campaign facts pinned back on.

    A direction may reword the *headline* freely — that is the creative work —
    but the call to action and the key message are campaign facts a human
    already confirmed. Taking the model's version of them would let a
    regeneration quietly rewrite the Campaign Specification, which is the one
    thing this system does not allow (PRODUCT_SPEC §1a).
    """
    data = proposed.model_dump()
    data.update(_pinned_facts(context, CreativeDirection))
    return CreativeDirection(
        campaign_id=context.campaign_id,
        ordinal=ordinal,
        negative_constraints=_negative_constraints(
            context, proposed.reference_characteristics_avoided
        ),
        **data,
    )


def _pinned_facts(context: CreativeContext, target: type[DomainModel]) -> dict[str, str]:
    """The confirmed campaign facts `target` is able to hold.

    Filtered by the target's own fields because the two creative models carry
    different subsets — a direction restates the key message, a specification
    does not — and the rest of `PROTECTED_CAMPAIGN_FACTS` lives on the Campaign
    Specification alone and is never copied here at all.
    """
    specification = context.specification
    if specification is None:
        return {}
    facts = {"cta": specification.cta, "key_message": specification.key_message}
    return {name: value for name, value in facts.items() if name in target.model_fields}


def _default_reasons(context: CreativeContext, direction: CreativeDirection) -> list[str]:
    """A concise, user-facing account of the recommendation.

    A decision summary, never reasoning traces (CLAUDE.md rule 8).
    """
    reasons: list[str] = []
    if context.specification is not None:
        reasons.append(f"Matches the objective: {context.specification.objective[:80]}")
        reasons.append(f"Speaks to {context.specification.audience[:60]}")
    if context.guardrails.tone_attributes:
        tone = ", ".join(context.guardrails.tone_attributes[:3])
        reasons.append(f"Sits with the brand tone: {tone}")
    if context.style_profile.weights:
        reasons.append(f"Reflects your visual preference: {context.style_profile.describe()}")
    if context.reference_style.reference_count:
        reasons.append(
            f"Uses reference qualities from {context.reference_style.reference_count} reference(s)"
        )
    return reasons[:5]


def protected_keep_list(context: CreativeContext) -> list[str]:
    """Campaign facts a creative revision may never change.

    Feedback about tone or imagery has no business altering the product, the
    audience or an approved claim.
    """
    return list(PROTECTED_CAMPAIGN_FACTS)
