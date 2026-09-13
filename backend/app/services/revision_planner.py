"""The Revision Planner.

Turns a sentence of human feedback into a structured `RevisionDelta`: the
fields to change, the fields to keep, and why.

**It plans; it does not rewrite.** The model is asked for a *delta*, never for a
new specification. Handed "here is the plan, return a better one", a model
restates everything, and the parts a human already approved disappear into a
diff nobody can read. Asking only for the change is what makes the revision
reviewable before it runs.

**Locked fields need an explicit request.** The call to action, how the product
is shown, how the brand appears and the constraints that keep the plate usable
may be changed — a user is allowed to change their mind — but only when the
feedback actually asked. `_explicit_unlocks` decides that from the user's own
words, in code, so a model cannot talk its way into one.

**Unclear feedback goes back to the human.** A planner that guessed would
produce a confident revision of something nobody asked for, which is worse than
saying "we could not tell what this is about".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import Field

from app.domain.campaign import CampaignBrief
from app.domain.common import DomainModel
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.generation import GeneratedAsset
from app.domain.revision import (
    LOCKED_FIELDS,
    FieldChange,
    RevisionAction,
    RevisionDelta,
)
from app.logging import get_logger
from app.providers.base import LLMProvider, ProviderInvalidResponse

log = get_logger(__name__)

#: Fields a revision is allowed to write. Everything else on a
#: `CreativeSpecification` is either identity, provenance, or derived — and a
#: delta naming one is a planner that has misunderstood its job.
REVISABLE_FIELDS: tuple[str, ...] = (
    "concept",
    "visual_story",
    "emotional_angle",
    "headline",
    "headline_guidance",
    "subhead",
    "cta",
    "cta_guidance",
    "body_copy",
    "visual_metaphor",
    "composition",
    "focal_point",
    "subject",
    "environment",
    "lighting",
    "camera",
    "palette",
    "color_direction",
    "mood",
    "product_integration",
    "people_guidance",
    "brand_integration",
    "regional_cues",
    "negative_constraints",
)

#: A locked field is only unlocked when the feedback names it in the user's own
#: words. Matched in code, never inferred by the model.
_UNLOCK_CUES: dict[str, str] = {
    "cta": r"\b(call to action|cta|button|ask)\b",
    "cta_guidance": r"\b(call to action|cta)\b",
    "product_integration": r"\b(product|the item|the system)\b",
    "brand_integration": r"\b(brand|logo|identity)\b",
    "negative_constraints": r"\b(constraint|restriction|allow|forbid)\b",
}

PLANNER_SYSTEM = (
    "You turn a marketer's feedback into a precise, minimal change to an "
    "approved creative plan. "
    "Name only the fields the feedback is actually about, and give each one a "
    "concrete replacement value. Name the fields you are leaving alone. "
    "Never rewrite the whole plan, never invent new campaign facts, and never "
    "change the call to action, the product framing or the brand framing unless "
    "the feedback explicitly asks for it. "
    "If the feedback is too vague to act on, return no changes and say so. "
    "Never include reasoning traces."
)


class ProposedFieldChange(DomainModel):
    field: str = Field(min_length=1, max_length=60)
    action: RevisionAction = RevisionAction.CHANGE
    reason: str = Field(default="", max_length=300)
    new_value: str | None = Field(default=None, max_length=1200)


class ProposedRevision(DomainModel):
    """The model's output. Validated, never trusted raw.

    Carries no iteration, no version and no unlocks — those are decided by the
    service from facts it holds, not by the model.
    """

    interpretation: str = Field(default="", max_length=600)
    keep: list[str] = Field(default_factory=list, max_length=40)
    change: list[ProposedFieldChange] = Field(default_factory=list, max_length=20)
    add: list[ProposedFieldChange] = Field(default_factory=list, max_length=10)
    remove: list[ProposedFieldChange] = Field(default_factory=list, max_length=10)
    explicit_unlocks: list[str] = Field(default_factory=list, max_length=10)
    rationale: str = Field(default="", max_length=600)


@dataclass(frozen=True)
class RevisionContext:
    """Everything the planner needs, from scope-checked rows only."""

    specification: CreativeSpecification
    feedback: str
    iteration: int = 1
    campaign: CampaignBrief | None = None
    guardrails: BrandGuardrails = field(default_factory=BrandGuardrails)
    asset: GeneratedAsset | None = None
    #: What the evaluator and guardian already found. Context for the planner,
    #: never instructions — the human's feedback is what is being acted on.
    evaluation_concerns: list[str] = field(default_factory=list)
    guardian_fixes: list[str] = field(default_factory=list)


class FeedbackTooVague(ValueError):
    """The planner could not tell what the feedback was about.

    Raised rather than guessing: a confident revision of something nobody asked
    for is worse than an honest question.
    """


def explicit_unlocks(feedback: str) -> list[str]:
    """Which locked fields the feedback actually asked to change.

    Decided from the user's words in code. A model that wanted to change the
    call to action cannot grant itself permission by claiming the user meant it.
    """
    lowered = feedback.lower()
    return [
        name
        for name in LOCKED_FIELDS
        if name in _UNLOCK_CUES and re.search(_UNLOCK_CUES[name], lowered)
    ]


def build_planner_prompt(context: RevisionContext) -> str:
    """The brief: the current plan, the feedback, and the rules of engagement."""
    specification = context.specification
    lines: list[str] = [
        "Turn this feedback into the smallest correct change to the approved plan.",
        "",
        f"FEEDBACK: {context.feedback}",
        "",
        f"CURRENT CREATIVE SPECIFICATION (version {specification.version}):",
        f"concept: {specification.concept}",
        f"visual_story: {specification.visual_story}",
        f"emotional_angle: {specification.emotional_angle}",
        f"subject: {specification.subject}",
        f"environment: {specification.environment}",
        f"composition: {specification.composition}",
        f"focal_point: {specification.focal_point}",
        f"lighting: {specification.lighting}",
        f"color_direction: {specification.color_direction}",
        f"mood: {', '.join(specification.mood)}",
        f"people_guidance: {specification.people_guidance}",
        f"headline: {specification.headline}",
        f"cta: {specification.cta}",
        f"product_integration: {specification.product_integration}",
        f"brand_integration: {specification.brand_integration}",
    ]

    if context.campaign is not None:
        lines += [
            "",
            "APPROVED CAMPAIGN FACTS — these never change here:",
            f"objective: {context.campaign.objective}",
            f"audience: {context.campaign.audience}",
            f"product: {context.campaign.product}",
            f"key message: {context.campaign.key_message}",
        ]
    if context.guardrails.prohibited_claims:
        lines.append(f"NEVER IMPLY: {'; '.join(context.guardrails.prohibited_claims)}")

    if context.guardian_fixes:
        lines += ["", "THE BRAND CHECK SUGGESTED: " + "; ".join(context.guardian_fixes[:3])]
    if context.evaluation_concerns:
        lines += ["", "THE CREATIVE REVIEW NOTED: " + "; ".join(context.evaluation_concerns[:3])]

    unlocked = explicit_unlocks(context.feedback)
    locked_now = [name for name in LOCKED_FIELDS if name not in unlocked]
    lines += [
        "",
        f"FIELDS YOU MAY CHANGE: {', '.join(REVISABLE_FIELDS)}",
        f"FIELDS THAT ARE LOCKED: {', '.join(locked_now)}",
    ]
    if unlocked:
        lines.append(
            f"The feedback explicitly asks about these, so they may change: {', '.join(unlocked)}"
        )
    lines += [
        "",
        "Change as little as possible. Name every field you are leaving alone.",
    ]
    return "\n".join(lines)


class RevisionPlanner:
    """Feedback in, a reviewable delta out."""

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def plan(self, context: RevisionContext) -> RevisionDelta:
        """Interpret the feedback.

        Raises `FeedbackTooVague` when nothing actionable came back, and
        `ProviderError` when the model call failed.
        """
        if not context.feedback.strip():
            raise FeedbackTooVague("Tell us what you would change.")

        proposed = await self.llm.structured(
            build_planner_prompt(context), ProposedRevision, system=PLANNER_SYSTEM
        )

        unlocked = explicit_unlocks(context.feedback)
        change = _clean(proposed.change, RevisionAction.CHANGE, unlocked)
        add = _clean(proposed.add, RevisionAction.ADD, unlocked)
        remove = _clean(proposed.remove, RevisionAction.REMOVE, unlocked)

        if not (change or add or remove):
            raise FeedbackTooVague(
                "We could not tell which part of the creative this is about. "
                "Naming what to keep and what to change helps — for example: "
                "'keep the composition, but make the environment feel more local'."
            )

        touched = {item.field for item in (*change, *add, *remove)}
        delta = RevisionDelta(
            iteration=context.iteration,
            user_feedback=context.feedback,
            interpretation=proposed.interpretation,
            # Whatever the model claimed to keep, minus anything it then
            # changed — the model's two lists are not required to agree, and
            # the delta's own validator would reject a contradiction.
            keep=sorted(set(proposed.keep) - touched),
            change=change,
            add=add,
            remove=remove,
            explicit_unlocks=unlocked,
            rationale=proposed.rationale,
        )
        log.info(
            "revision_planned",
            iteration=context.iteration,
            changed=sorted(touched),
            unlocked=unlocked,
        )
        return delta


def _clean(
    proposed: list[ProposedFieldChange], action: RevisionAction, unlocked: list[str]
) -> list[FieldChange]:
    """Keep only the instructions this planner is allowed to act on.

    Dropped rather than rejected: a model naming one unknown field alongside
    three good ones should produce three good changes, not an error. A locked
    field reached for without permission is dropped here too, so the delta that
    reaches the user is one the system will actually apply.
    """
    kept: list[FieldChange] = []
    seen: set[str] = set()
    for item in proposed:
        name = item.field.strip()
        if name not in REVISABLE_FIELDS or name in seen:
            continue
        if name in LOCKED_FIELDS and name not in unlocked:
            log.info("revision_locked_field_dropped", field=name)
            continue
        if action in (RevisionAction.CHANGE, RevisionAction.ADD) and not item.new_value:
            continue
        seen.add(name)
        kept.append(
            FieldChange(
                field=name,
                action=action,
                reason=item.reason or "Addresses your feedback.",
                new_value=item.new_value,
            )
        )
    return kept


def validate_delta(delta: RevisionDelta) -> RevisionDelta:
    """Re-check a delta a human has edited.

    The UI lets a user change the plan before approving it, which means the
    delta can arrive with fields the planner never proposed. Everything the
    planner enforces has to hold for an edited delta too, or the edit becomes
    the way around the rules.
    """
    for item in (*delta.change, *delta.add, *delta.remove):
        if item.field not in REVISABLE_FIELDS:
            raise ProviderInvalidResponse(
                f"{item.field} is not a field of the creative plan.", provider="revision"
            )
    return delta
