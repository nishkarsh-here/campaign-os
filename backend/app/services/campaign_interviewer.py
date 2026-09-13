"""The Campaign Interviewer.

Its job is to ask the *best next question*, not to run a questionnaire. Three
rules shape it:

1. **High-impact first.** Objective before typography, audience before
   decoration, message before layout. `FIELD_PRIORITY` encodes that order.
2. **Never re-ask.** A field with a value — or one the user said does not
   apply — is closed.
3. **Ask the Brand Brain first.** If the brand already answers a question, the
   interviewer does not ask it cold; it asks whether *this campaign* differs.

The model chooses and phrases the question; a deterministic guardrail then
checks its choice. If it picks something already answered, out of scope, or
low-value while a HIGH field is still open, the guardrail overrides it. That
split is deliberate: the phrasing benefits from a model, but "never repeats a
question" should be a property of the system, not something we hope for.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from pydantic import Field

from app.domain.brand import BrandKnowledge, BrandProfile
from app.domain.campaign import (
    Availability,
    CampaignInputs,
    Certainty,
    ConversationTurn,
    FieldAssertion,
    InterviewQuestion,
    QuestionPriority,
)
from app.domain.common import Channel, DomainModel
from app.providers.base import LLMProvider, ProviderError


@dataclass(frozen=True)
class FieldSpec:
    """What the interviewer knows about one campaign field."""

    name: str
    priority: QuestionPriority
    prompt: str
    why: str
    #: Where a brand-level answer would come from, if the Brand Brain has one.
    brand_attribute: str | None = None
    options: tuple[str, ...] = ()
    is_list: bool = False


#: Ordered by impact on the eventual creative. The interview walks this list.
FIELD_PRIORITY: tuple[FieldSpec, ...] = (
    FieldSpec(
        "campaign_objective",
        QuestionPriority.HIGH,
        "What should this campaign achieve?",
        "The objective decides everything else — the message, the channels, the call to action.",
        options=(
            "awareness",
            "product launch",
            "lead generation",
            "engagement",
            "retention",
            "conversion",
        ),
    ),
    FieldSpec(
        "product",
        QuestionPriority.HIGH,
        "What product or service is this campaign for?",
        "The creative has to show something specific.",
        brand_attribute="products",
    ),
    FieldSpec(
        "target_audience",
        QuestionPriority.HIGH,
        "Who is this campaign speaking to?",
        "Audience changes the tone, the imagery and the proof points.",
        brand_attribute="audience_description",
    ),
    FieldSpec(
        "key_message",
        QuestionPriority.HIGH,
        "What is the one thing the audience should take away?",
        "One clear message beats several competing ones.",
    ),
    FieldSpec(
        "channels",
        QuestionPriority.HIGH,
        "Where will this run?",
        "Each channel has its own shape and reading distance.",
        options=tuple(c.value for c in Channel),
        is_list=True,
    ),
    FieldSpec(
        "cta",
        QuestionPriority.MEDIUM,
        "What should someone do after seeing this?",
        "Without a call to action the campaign has no next step.",
    ),
    FieldSpec(
        "desired_emotional_response",
        QuestionPriority.MEDIUM,
        "How should this make the audience feel?",
        "Emotional intent drives art direction more than any adjective about style.",
    ),
    FieldSpec(
        "key_offer",
        QuestionPriority.MEDIUM,
        "Is there a specific offer or value proposition to lead with?",
        "A concrete offer gives the creative something to promise.",
    ),
    FieldSpec(
        "region",
        QuestionPriority.MEDIUM,
        "Which market or region is this for?",
        "Regional context changes what reads as credible.",
    ),
    FieldSpec(
        "campaign_tone",
        QuestionPriority.MEDIUM,
        "Should this campaign sound like your usual brand tone, or shift for this one?",
        "A launch and a retention campaign rarely want the same voice.",
        brand_attribute="voice.tone_attributes",
        is_list=True,
    ),
    FieldSpec(
        "timing_occasion",
        QuestionPriority.LOW,
        "Is this tied to a season, event or deadline?",
        "Timing can change the imagery and the urgency.",
    ),
    FieldSpec(
        "required_elements",
        QuestionPriority.LOW,
        "Anything that must appear — a logo lockup, a legal line, a product shot?",
        "Required elements are cheaper to plan for than to retrofit.",
        is_list=True,
    ),
    FieldSpec(
        "avoid_restrictions",
        QuestionPriority.LOW,
        "Anything to avoid in this campaign specifically?",
        "Campaign-level restrictions sit on top of your brand rules.",
        is_list=True,
    ),
)

FIELDS_BY_NAME = {spec.name: spec for spec in FIELD_PRIORITY}
_PRIORITY_RANK = {QuestionPriority.HIGH: 0, QuestionPriority.MEDIUM: 1, QuestionPriority.LOW: 2}

#: The interview may end once every HIGH field is settled. Chasing MEDIUM and
#: LOW fields to exhaustion is what makes a discovery conversation feel like
#: the form it was meant to replace.
SUFFICIENT_PRIORITIES = (QuestionPriority.HIGH,)


# --------------------------------------------------------------------------
# LLM output schemas — validated, never trusted raw
# --------------------------------------------------------------------------
class ProposedQuestion(DomainModel):
    """What the model returns when asked for the next question."""

    field: str
    question: str = Field(min_length=5, max_length=400)
    why: str = Field(min_length=3, max_length=300)
    priority: QuestionPriority = QuestionPriority.MEDIUM


class FieldUpdate(DomainModel):
    field: str
    #: Rendered as text; the service coerces it to the typed field.
    value: str = Field(default="", max_length=2000)
    certainty: Certainty = Certainty.STATED
    not_applicable: bool = False


class AnswerExtraction(DomainModel):
    """What the model understood from one user reply."""

    updates: list[FieldUpdate] = Field(default_factory=list, max_length=20)
    #: Left unresolved on purpose when the reply did not actually answer.
    unresolved: list[str] = Field(default_factory=list, max_length=20)


@dataclass
class InterviewPlan:
    """The interviewer's decision for this turn."""

    complete: bool
    question: InterviewQuestion | None = None
    missing: list[str] = dataclass_field(default_factory=list)


def brand_default_for(spec: FieldSpec, brand: BrandProfile | None) -> str | None:
    """A brand-level answer, if the Brand Brain already has one.

    Returned so the question can become "is this campaign different?" rather
    than asking something the brand already answers.
    """
    if brand is None or spec.brand_attribute is None:
        return None
    value: object = brand
    for part in spec.brand_attribute.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    if isinstance(value, list):
        if not value:
            return None
        rendered = [getattr(v, "name", None) or str(v) for v in value]
        return ", ".join(rendered[:5])
    return str(value) or None


def open_fields(inputs: CampaignInputs) -> list[FieldSpec]:
    """Fields still worth asking about, highest impact first."""
    answered = inputs.answered_fields()
    return sorted(
        (spec for spec in FIELD_PRIORITY if spec.name not in answered),
        key=lambda s: _PRIORITY_RANK[s.priority],
    )


def is_sufficient(inputs: CampaignInputs) -> bool:
    """Enough to build a specification: every HIGH field settled."""
    return not [s for s in open_fields(inputs) if s.priority in SUFFICIENT_PRIORITIES]


class CampaignInterviewer:
    """Chooses the next question, and interprets the answer."""

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def plan(
        self,
        *,
        inputs: CampaignInputs,
        brand: BrandProfile | None,
        knowledge: BrandKnowledge | None,
        conversation: list[ConversationTurn],
    ) -> InterviewPlan:
        remaining = open_fields(inputs)
        if is_sufficient(inputs):
            return InterviewPlan(complete=True, missing=[s.name for s in remaining])
        if not remaining:
            return InterviewPlan(complete=True)

        target = remaining[0]
        proposed = await self._propose(target, remaining, inputs, brand, knowledge, conversation)
        spec = FIELDS_BY_NAME[proposed.field]
        default = brand_default_for(spec, brand)

        return InterviewPlan(
            complete=False,
            question=InterviewQuestion(
                field=spec.name,
                question=proposed.question,
                why=proposed.why,
                priority=spec.priority,
                options=list(spec.options),
                required=spec.priority is QuestionPriority.HIGH,
                brand_default=default,
            ),
            missing=[s.name for s in remaining],
        )

    async def _propose(
        self,
        target: FieldSpec,
        remaining: list[FieldSpec],
        inputs: CampaignInputs,
        brand: BrandProfile | None,
        knowledge: BrandKnowledge | None,
        conversation: list[ConversationTurn],
    ) -> ProposedQuestion:
        """Ask the model, then enforce the guardrail on what it chose."""
        allowed = {s.name for s in remaining}
        try:
            proposed = await self.llm.structured(
                self._question_prompt(target, remaining, inputs, brand, knowledge, conversation),
                ProposedQuestion,
                system=(
                    "You are a marketing consultant running a short discovery "
                    "conversation. Ask one question at a time, in plain language."
                ),
            )
        except ProviderError:
            # A model failure must not stall discovery — fall back to the
            # deterministic question for the highest-impact open field.
            return ProposedQuestion(
                field=target.name,
                question=target.prompt,
                why=target.why,
                priority=target.priority,
            )

        # The guardrail. A model that picks an answered field, an unknown
        # field, or a LOW field while a HIGH one is open gets overridden.
        if proposed.field not in allowed:
            return ProposedQuestion(
                field=target.name,
                question=target.prompt,
                why=target.why,
                priority=target.priority,
            )
        chosen = FIELDS_BY_NAME[proposed.field]
        if _PRIORITY_RANK[chosen.priority] > _PRIORITY_RANK[target.priority]:
            return ProposedQuestion(
                field=target.name,
                question=target.prompt,
                why=target.why,
                priority=target.priority,
            )
        return proposed

    def _question_prompt(
        self,
        target: FieldSpec,
        remaining: list[FieldSpec],
        inputs: CampaignInputs,
        brand: BrandProfile | None,
        knowledge: BrandKnowledge | None,
        conversation: list[ConversationTurn],
    ) -> str:
        known = {
            name: getattr(inputs, name)
            for name in type(inputs).model_fields
            if name != "assertions" and getattr(inputs, name) not in (None, "", [], {})
        }
        default = brand_default_for(target, brand)
        lines = [
            f"NEXT FIELD TO ASK ABOUT: {target.name}",
            f"SUGGESTED WORDING: {target.prompt}",
            f"WHY IT MATTERS: {target.why}",
            f"STILL OPEN: {', '.join(s.name for s in remaining)}",
            f"ALREADY KNOWN: {known or 'nothing yet'}",
        ]
        if brand is not None:
            lines.append(f"BRAND: {brand.name}")
        if default:
            # The behaviour the milestone asks for: confirm or differentiate,
            # rather than asking something the brand already answers.
            lines.append(
                f"THE BRAND ALREADY SAYS {target.name} = {default!r}. "
                "Ask whether this campaign keeps that or differs — do not ask from scratch."
            )
        if knowledge and knowledge.chunks:
            lines.append(f"BRAND KNOWLEDGE:\n{knowledge.as_context(1500)}")
        if conversation:
            recent = conversation[-6:]
            lines.append(
                "RECENT CONVERSATION:\n" + "\n".join(f"{t.role}: {t.content}" for t in recent)
            )
        lines.append("Ask exactly one question about the field above.")
        return "\n\n".join(lines)

    async def interpret(
        self, *, answer: str, question: InterviewQuestion | None, inputs: CampaignInputs
    ) -> AnswerExtraction:
        """Turn a free-text reply into typed field updates."""
        asked = question.field if question else "unknown"
        prompt = (
            f"QUESTION ASKED (about field {asked!r}): "
            f"{question.question if question else 'open conversation'}\n\n"
            f"USER REPLY: {answer}\n\n"
            f"FIELDS YOU MAY SET: {', '.join(FIELDS_BY_NAME)}\n\n"
            "Extract only what the reply actually says. Mark a value 'inferred' "
            "when you are reading between the lines, and 'stated' only when the "
            "user said it. If the reply says the field does not apply, set "
            "not_applicable."
        )
        return await self.llm.structured(
            prompt,
            AnswerExtraction,
            system=(
                "You convert a marketer's natural reply into structured campaign "
                "fields. Never invent a value the reply does not support."
            ),
        )


def apply_updates(
    inputs: CampaignInputs, extraction: AnswerExtraction, *, source: str = "you said"
) -> CampaignInputs:
    """Merge extracted updates into the typed inputs.

    A field a human has edited is never overwritten here — that protection is
    the same promise the specification makes downstream.
    """
    data = inputs.model_dump()
    assertions = dict(inputs.assertions)

    for update in extraction.updates:
        spec = FIELDS_BY_NAME.get(update.field)
        if spec is None:
            continue  # the model named a field that is not ours
        existing = assertions.get(update.field)
        if existing and existing.edited_by_human:
            continue

        if update.not_applicable:
            assertions[update.field] = FieldAssertion(
                field=update.field,
                availability=Availability.NOT_APPLICABLE,
                certainty=Certainty.STATED,
                source=source,
            )
            continue
        if not update.value.strip():
            continue

        data[update.field] = _coerce(spec, update.value)
        assertions[update.field] = FieldAssertion(
            field=update.field,
            availability=Availability.KNOWN,
            certainty=update.certainty,
            source=source,
        )

    for name in extraction.unresolved:
        if name in FIELDS_BY_NAME and name not in assertions:
            assertions[name] = FieldAssertion(
                field=name, availability=Availability.UNKNOWN, certainty=Certainty.UNRESOLVED
            )

    data["assertions"] = assertions
    return CampaignInputs.model_validate(data)


def _coerce(spec: FieldSpec, value: str) -> object:
    """Text into the field's declared type."""
    if spec.name == "channels":
        # People answer "LinkedIn and an Instagram post", not "linkedin,
        # instagram_post". Match channel names as they appear in the sentence.
        text = value.lower().replace("-", " ").replace("_", " ")
        matched = [c for c in Channel if c.value.replace("_", " ") in text]
        if not matched:
            # A bare platform name: "instagram" means the post format.
            matched = [c for c in Channel if c.value.split("_")[0] in text]
        return list(dict.fromkeys(matched))
    if spec.is_list:
        return [part.strip() for part in value.split(",") if part.strip()]
    return value.strip()
