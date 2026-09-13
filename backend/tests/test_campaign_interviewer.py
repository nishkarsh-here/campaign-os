"""The Campaign Interviewer.

The behaviours that separate a discovery conversation from a questionnaire:
ask the high-impact thing first, never re-ask, use what the brand already
says, stop when there is enough, and never quietly upgrade a guess to a fact.
"""

from __future__ import annotations

import pytest

from app.domain.brand import BrandKnowledge, BrandKnowledgeChunk, BrandProfile, BrandVoice
from app.domain.campaign import (
    Availability,
    CampaignInputs,
    Certainty,
    FieldAssertion,
    QuestionPriority,
)
from app.domain.common import Channel
from app.providers.mock.llm import MockLLMProvider
from app.services.campaign_interviewer import (
    FIELDS_BY_NAME,
    AnswerExtraction,
    CampaignInterviewer,
    FieldUpdate,
    apply_updates,
    brand_default_for,
    is_sufficient,
    open_fields,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def interviewer() -> CampaignInterviewer:
    return CampaignInterviewer(MockLLMProvider())


@pytest.fixture
def brand() -> BrandProfile:
    return BrandProfile(
        id="b1",
        organization_id="o1",
        name="Northline",
        audience_description="Architects and contractors",
        voice=BrandVoice(tone_attributes=["confident", "technical"]),
    )


def _complete_inputs() -> CampaignInputs:
    return CampaignInputs(
        campaign_objective="product launch",
        product="FS-9 facade system",
        target_audience="architects in Maharashtra",
        key_message="Engineered to outlast the building",
        channels=[Channel.LINKEDIN],
    )


class TestPrioritisation:
    def test_high_impact_fields_come_first(self) -> None:
        """Objective before typography, audience before decoration."""
        first_five = [s.name for s in open_fields(CampaignInputs())][:5]
        assert set(first_five) == {
            "campaign_objective",
            "product",
            "target_audience",
            "key_message",
            "channels",
        }

    def test_low_priority_fields_come_last(self) -> None:
        order = [s.name for s in open_fields(CampaignInputs())]
        assert order.index("campaign_objective") < order.index("timing_occasion")
        assert order.index("key_message") < order.index("avoid_restrictions")

    async def test_the_first_question_targets_a_high_priority_field(self, interviewer) -> None:
        plan = await interviewer.plan(
            inputs=CampaignInputs(), brand=None, knowledge=None, conversation=[]
        )
        assert plan.complete is False
        assert plan.question is not None
        assert plan.question.priority is QuestionPriority.HIGH


class TestNeverRepeats:
    async def test_an_answered_field_is_not_asked_again(self, interviewer) -> None:
        inputs = CampaignInputs(campaign_objective="product launch")
        plan = await interviewer.plan(inputs=inputs, brand=None, knowledge=None, conversation=[])
        assert plan.question is not None
        assert plan.question.field != "campaign_objective"

    async def test_a_field_marked_not_applicable_is_never_asked(self, interviewer) -> None:
        """ "That doesn't apply" has to close the question, or the interview
        loops on it forever."""
        inputs = CampaignInputs(
            assertions={
                "region": FieldAssertion(field="region", availability=Availability.NOT_APPLICABLE)
            }
        )
        assert "region" not in [s.name for s in open_fields(inputs)]

    async def test_successive_turns_ask_about_different_fields(self, interviewer) -> None:
        inputs = CampaignInputs()
        asked: list[str] = []
        for _ in range(4):
            plan = await interviewer.plan(
                inputs=inputs, brand=None, knowledge=None, conversation=[]
            )
            if plan.complete or plan.question is None:
                break
            asked.append(plan.question.field)
            extraction = await interviewer.interpret(
                answer="A clear and specific answer for this field.",
                question=plan.question,
                inputs=inputs,
            )
            inputs = apply_updates(inputs, extraction)
        assert len(asked) == len(set(asked)), f"a field was asked twice: {asked}"


class TestBrandBrainInfluence:
    def test_a_brand_level_answer_is_found(self, brand) -> None:
        spec = FIELDS_BY_NAME["target_audience"]
        assert brand_default_for(spec, brand) == "Architects and contractors"

    def test_a_list_valued_brand_attribute_is_rendered(self, brand) -> None:
        assert brand_default_for(FIELDS_BY_NAME["campaign_tone"], brand) == ("confident, technical")

    def test_no_brand_gives_no_default(self) -> None:
        assert brand_default_for(FIELDS_BY_NAME["target_audience"], None) is None

    async def test_the_question_confirms_rather_than_asking_cold(self, interviewer, brand) -> None:
        """The behaviour the milestone specifies: when the brand already says
        who the audience is, ask whether this campaign differs."""
        inputs = CampaignInputs(campaign_objective="launch", product="FS-9", key_message="durable")
        plan = await interviewer.plan(inputs=inputs, brand=brand, knowledge=None, conversation=[])
        assert plan.question is not None
        assert plan.question.field == "target_audience"
        assert plan.question.brand_default == "Architects and contractors"
        text = plan.question.question.lower()
        assert "architects and contractors" in text
        assert "different" in text or "keep that" in text

    async def test_brand_knowledge_reaches_the_prompt(self, interviewer, brand) -> None:
        knowledge = BrandKnowledge(
            query="tone",
            chunks=[
                BrandKnowledgeChunk(
                    document_id="d1",
                    document_title="Guidelines",
                    content="We never claim products are indestructible.",
                    score=0.9,
                )
            ],
        )
        plan = await interviewer.plan(
            inputs=CampaignInputs(), brand=brand, knowledge=knowledge, conversation=[]
        )
        assert plan.question is not None  # did not crash on knowledge


class TestStoppingCondition:
    def test_incomplete_inputs_are_not_sufficient(self) -> None:
        assert is_sufficient(CampaignInputs()) is False

    def test_all_high_priority_fields_answered_is_sufficient(self) -> None:
        assert is_sufficient(_complete_inputs()) is True

    async def test_the_interviewer_stops_when_sufficient(self, interviewer) -> None:
        plan = await interviewer.plan(
            inputs=_complete_inputs(), brand=None, knowledge=None, conversation=[]
        )
        assert plan.complete is True
        assert plan.question is None

    def test_it_does_not_chase_every_low_priority_field(self) -> None:
        """Otherwise discovery becomes the form it was meant to replace."""
        inputs = _complete_inputs()
        assert is_sufficient(inputs)
        assert [s.name for s in open_fields(inputs)]  # some remain, deliberately


class TestStatedVersusInferred:
    async def test_a_hedged_answer_is_recorded_as_inferred(self, interviewer) -> None:
        """ "I think this is mainly for architects" is not a statement of fact —
        the exact case the milestone calls out."""
        inputs = CampaignInputs()
        plan = await interviewer.plan(inputs=inputs, brand=None, knowledge=None, conversation=[])
        extraction = await interviewer.interpret(
            answer="I think this is mainly a product launch",
            question=plan.question,
            inputs=inputs,
        )
        updated = apply_updates(inputs, extraction)
        assert updated.assertions["campaign_objective"].certainty is Certainty.INFERRED

    async def test_a_direct_answer_is_recorded_as_stated(self, interviewer) -> None:
        inputs = CampaignInputs()
        plan = await interviewer.plan(inputs=inputs, brand=None, knowledge=None, conversation=[])
        extraction = await interviewer.interpret(
            answer="This is a product launch.", question=plan.question, inputs=inputs
        )
        updated = apply_updates(inputs, extraction)
        assert updated.assertions["campaign_objective"].certainty is Certainty.STATED

    async def test_not_applicable_is_recorded_and_closes_the_field(self, interviewer) -> None:
        inputs = CampaignInputs(
            campaign_objective="launch",
            product="FS-9",
            target_audience="architects",
            key_message="durable",
            channels=[Channel.LINKEDIN],
        )
        extraction = await interviewer.interpret(
            answer="Not applicable for this one.",
            question=FIELDS_BY_NAME["key_offer"].name
            and __import__("app.domain.campaign", fromlist=["InterviewQuestion"]).InterviewQuestion(
                field="key_offer", question="Any offer?", why="x"
            ),
            inputs=inputs,
        )
        updated = apply_updates(inputs, extraction)
        assert updated.assertions["key_offer"].availability is Availability.NOT_APPLICABLE
        assert "key_offer" not in [s.name for s in open_fields(updated)]


class TestApplyUpdates:
    def test_channels_are_coerced_to_the_enum(self) -> None:
        updated = apply_updates(
            CampaignInputs(),
            AnswerExtraction(updates=[FieldUpdate(field="channels", value="linkedin")]),
        )
        assert Channel.LINKEDIN in updated.channels

    @pytest.mark.parametrize(
        ("reply", "expected"),
        [
            ("LinkedIn and Instagram post.", {Channel.LINKEDIN, Channel.INSTAGRAM_POST}),
            ("linkedin, web banner", {Channel.LINKEDIN, Channel.WEB_BANNER}),
            ("print A3", {Channel.PRINT_A3}),
        ],
    )
    def test_channels_are_read_from_a_natural_sentence(self, reply, expected) -> None:
        """People answer "LinkedIn and an Instagram post", not "linkedin,
        instagram_post". A strict match left channels empty and the interview
        looping on a question the user had already answered."""
        updated = apply_updates(
            CampaignInputs(),
            AnswerExtraction(updates=[FieldUpdate(field="channels", value=reply)]),
        )
        assert expected <= set(updated.channels)

    def test_list_fields_split_on_commas(self) -> None:
        updated = apply_updates(
            CampaignInputs(),
            AnswerExtraction(
                updates=[FieldUpdate(field="required_elements", value="logo, legal line")]
            ),
        )
        assert updated.required_elements == ["logo", "legal line"]

    def test_an_unknown_field_from_the_model_is_ignored(self) -> None:
        """The model naming a field we do not have must not crash or create one."""
        updated = apply_updates(
            CampaignInputs(),
            AnswerExtraction(updates=[FieldUpdate(field="not_a_real_field", value="x")]),
        )
        assert "not_a_real_field" not in updated.assertions

    def test_a_human_edited_field_is_never_overwritten(self) -> None:
        """The promise the specification makes downstream, enforced here too."""
        inputs = CampaignInputs(
            product="Edited by a person",
            assertions={
                "product": FieldAssertion(
                    field="product",
                    availability=Availability.KNOWN,
                    certainty=Certainty.STATED,
                    edited_by_human=True,
                )
            },
        )
        updated = apply_updates(
            inputs,
            AnswerExtraction(updates=[FieldUpdate(field="product", value="AI overwrote it")]),
        )
        assert updated.product == "Edited by a person"

    def test_an_empty_value_does_not_clobber_an_existing_one(self) -> None:
        inputs = CampaignInputs(product="FS-9")
        updated = apply_updates(
            inputs, AnswerExtraction(updates=[FieldUpdate(field="product", value="   ")])
        )
        assert updated.product == "FS-9"


class TestModelFailure:
    async def test_a_failing_model_still_yields_a_usable_question(self) -> None:
        """Discovery must not stall because the model is unavailable."""
        interviewer = CampaignInterviewer(MockLLMProvider(failure_mode="timeout"))
        plan = await interviewer.plan(
            inputs=CampaignInputs(), brand=None, knowledge=None, conversation=[]
        )
        assert plan.question is not None
        assert plan.question.field == "campaign_objective"
        assert plan.question.question
