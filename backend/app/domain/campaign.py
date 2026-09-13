"""Campaign inputs and the CAMPAIGN SPECIFICATION.

`CampaignInputs` is what the interviewer extracts from conversation — the
structured form of "what the human wants". `CampaignBrief` is that resolved
against brand, references and market context: the complete, approved-in-spirit
statement of the campaign, and the input to the Creative Director.

The distinction matters: inputs can be incomplete (the interviewer is still
working), a brief cannot.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field, model_validator

from app.domain.common import Channel, DomainModel, Id, StyleFamily, new_id


class Certainty(StrEnum):
    """How we came to believe a campaign field.

    The distinction the milestone insists on: "I think this is mainly for
    architects" is not the same claim as a brand guideline saying so, and
    neither is the same as the model's own reading. Collapsing them is how a
    guess becomes a fact nobody agreed to.
    """

    STATED = "stated"  # the user said it, in their own words
    BRAND_DEFAULT = "brand_default"  # taken from the Brand Brain
    INFERRED = "inferred"  # the model's reading of the conversation
    UNRESOLVED = "unresolved"  # asked about, still not settled


class Availability(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"  # the user said it does not apply


class FieldAssertion(DomainModel):
    """What we believe about one campaign field, and on whose authority.

    Carried beside the values rather than wrapping them, so `CampaignInputs`
    stays a plain typed record that nodes can read without unwrapping — the
    same separation the Brand Brain uses for proposed facts.
    """

    field: str
    availability: Availability = Availability.UNKNOWN
    certainty: Certainty = Certainty.UNRESOLVED
    #: Short, user-facing: "you said", "from your brand guidelines".
    source: str | None = None
    #: True once a human has edited this field on the specification. AI
    #: recompilation must never overwrite it.
    edited_by_human: bool = False

    def is_authoritative(self) -> bool:
        """Stated by a human, or edited by one. Not a model's inference."""
        return self.edited_by_human or self.certainty in (
            Certainty.STATED,
            Certainty.BRAND_DEFAULT,
        )


class ConversationTurn(DomainModel):
    id: Id = Field(default_factory=new_id)
    role: str = Field(description="user | assistant | system")
    content: str
    # Which brief field this turn was trying to fill. Lets the UI show progress
    # and lets the interviewer avoid re-asking.
    targets_field: str | None = None


class QuestionPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InterviewQuestion(DomainModel):
    """A question the interviewer wants to ask.

    `why` is shown to the user — people answer better when they know what the
    answer changes, and it keeps the interview from feeling like a form. It is
    a one-line justification, never reasoning traces (CLAUDE.md rule 8).
    """

    id: Id = Field(default_factory=new_id)
    field: str
    question: str
    why: str
    priority: QuestionPriority = QuestionPriority.MEDIUM
    options: list[str] = Field(default_factory=list)
    required: bool = True
    #: Set when the Brand Brain already has a brand-level answer: the question
    #: then asks whether this campaign differs, rather than asking from scratch.
    brand_default: str | None = None


class CampaignInputs(DomainModel):
    """Structured campaign requirements. Every field optional *while gathering*;
    `REQUIRED_FIELDS` defines when gathering is done."""

    campaign_objective: str | None = None
    target_audience: str | None = None
    product: str | None = None
    key_message: str | None = None
    region: str | None = None
    language: str = "en"
    tone: list[str] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    visual_preferences: list[StyleFamily] = Field(default_factory=list)
    reference_style: str | None = None
    market_context: str | None = None
    constraints: list[str] = Field(default_factory=list)
    brand_requirements: list[str] = Field(default_factory=list)
    cta: str | None = None
    deadline: str | None = None
    budget_note: str | None = None

    # --- Milestone 3 discovery fields ---------------------------------
    desired_emotional_response: str | None = None
    campaign_tone: list[str] = Field(
        default_factory=list, description="Tone for THIS campaign; may differ from brand tone."
    )
    key_offer: str | None = Field(default=None, description="The offer or value proposition.")
    timing_occasion: str | None = None
    required_elements: list[str] = Field(default_factory=list)
    avoid_restrictions: list[str] = Field(default_factory=list)

    #: field name -> how we came to believe it. Absent means never addressed.
    assertions: dict[str, FieldAssertion] = Field(default_factory=dict)

    #: The interview may not end until these are populated. Deliberately short —
    #: every extra required field is another question the user has to answer.
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "campaign_objective",
        "target_audience",
        "product",
        "key_message",
        "channels",
    )

    def missing_required(self) -> list[str]:
        """Required fields with no value — unless the user said they do not apply."""
        missing: list[str] = []
        for name in self.REQUIRED_FIELDS:
            assertion = self.assertions.get(name)
            if assertion and assertion.availability is Availability.NOT_APPLICABLE:
                continue
            value = getattr(self, name)
            if value is None or (isinstance(value, list | str) and len(value) == 0):
                missing.append(name)
        return missing

    def answered_fields(self) -> set[str]:
        """Fields the interviewer must not ask about again.

        A field counts as answered once it has a value *or* the user has said
        it does not apply — re-asking either is the behaviour that makes an
        interview feel like a form.
        """
        answered: set[str] = set()
        for name in type(self).model_fields:
            if name == "assertions":
                continue
            value = getattr(self, name, None)
            if value not in (None, "", [], {}):
                answered.add(name)
        answered |= {
            field
            for field, a in self.assertions.items()
            if a.availability is Availability.NOT_APPLICABLE
        }
        return answered

    def human_edited_fields(self) -> set[str]:
        """Fields a human has edited. AI recompilation must preserve these."""
        return {f for f, a in self.assertions.items() if a.edited_by_human}

    def is_sufficient(self) -> bool:
        return not self.missing_required()


class CampaignBrief(DomainModel):
    """**The Campaign Specification** — the single source of truth for a campaign.

    Not a summary of the conversation: a synthesis of conversation + brand +
    references + market context, with everything ambiguous resolved. Everything
    downstream (directions, creative specification, prompts, assets) derives
    from this, and nothing downstream may contradict it.

    The canonical business concept is **CAMPAIGN SPECIFICATION**. The class is
    named `CampaignBrief` because that is the term the UI, the API and
    marketing teams use, and because `CampaignSpecification` sitting beside
    `CreativeSpecification` reads as two halves of one object rather than two
    stages. `CampaignSpecification` below is a real alias of this class, so
    either name works in code. See `docs/PRODUCT_SPEC.md` §1a.
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    version: int = 1

    title: str
    objective: str
    audience: str
    audience_insight: str | None = Field(
        default=None, description="What we believe about this audience that shapes the work."
    )
    product: str
    key_message: str
    supporting_messages: list[str] = Field(default_factory=list)
    cta: str

    region: str | None = None
    language: str = "en"
    channels: list[Channel] = Field(min_length=1)
    tone: list[str] = Field(default_factory=list)

    brand_requirements: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)

    # --- Milestone 3 discovery fields ---------------------------------
    desired_emotional_response: str | None = None
    campaign_tone: list[str] = Field(default_factory=list)
    key_offer: str | None = None
    timing_occasion: str | None = None
    required_elements: list[str] = Field(default_factory=list)
    avoid_restrictions: list[str] = Field(default_factory=list)

    #: field -> how we came to believe it. This is what makes "the user said
    #: this" distinguishable from "the model inferred this" downstream, and
    #: what protects a human edit from the next recompilation.
    field_assertions: dict[str, FieldAssertion] = Field(default_factory=dict)

    #: Written for the user: how the interview became this brief.
    rationale: str | None = None
    #: True when the interviewer hit its question cap rather than completing.
    assumptions_made: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _non_empty_core(self) -> CampaignBrief:
        for field in ("objective", "audience", "product", "key_message", "cta"):
            if not getattr(self, field).strip():
                raise ValueError(f"CampaignBrief.{field} must not be empty")
        return self


#: Canonical-vocabulary alias. `CampaignSpecification is CampaignBrief` — the
#: same class under the business name, so the mapping is executable rather than
#: a promise in a document. Asserted by `tests/test_domain_schemas.py`.
CampaignSpecification = CampaignBrief
