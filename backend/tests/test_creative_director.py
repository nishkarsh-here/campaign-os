"""The Creative Director: diversity, domain validation, and the IP boundary."""

from __future__ import annotations

import pytest

from app.domain.campaign import CampaignBrief
from app.domain.common import Channel
from app.domain.creative import (
    PROTECTED_CAMPAIGN_FACTS,
    CreativeDirection,
    CreativeDirectionSet,
    CreativeRevisionDelta,
    CreativeSpecification,
)
from app.domain.creative_context import BrandGuardrails, CreativeContext
from app.providers.base import ProviderInvalidResponse
from app.providers.mock.llm import MockLLMProvider
from app.services.creative_director import (
    SIMILARITY_LIMIT,
    CreativeDirector,
    assess_diversity,
    build_director_prompt,
)

pytestmark = pytest.mark.unit


def _direction(ordinal: int, **overrides) -> CreativeDirection:
    base = {
        "campaign_id": "c1",
        "ordinal": ordinal,
        "title": f"Direction {ordinal}",
        "big_idea": "An idea",
        "strategic_rationale": "Because it fits",
        "emotional_angle": "engineering confidence",
        "headline": "Built to outlast",
        "cta": "Request a pack",
        "visual_metaphor": "weathered context beside new work",
        "composition": "low angle facade filling the frame",
        "subject": "completed facade on an office building",
        "environment": "wet street after monsoon rain",
        "lighting": "directional late afternoon sun",
        "brand_integration": "graphite and signal accent",
        "product_integration": "the facade is the hero",
    }
    return CreativeDirection.model_validate(base | overrides)


def _context() -> CreativeContext:
    return CreativeContext(
        campaign_id="c1",
        specification=CampaignBrief(
            campaign_id="c1",
            title="Launch",
            objective="Establish the premium specification choice",
            audience="Architects in Maharashtra",
            product="FS-9 facade system",
            key_message="Engineered to outlast the building it clads",
            cta="Request a specification pack",
            channels=[Channel.LINKEDIN],
            region="Maharashtra, India",
        ),
        brand_name="Northline",
        guardrails=BrandGuardrails(
            tone_attributes=["confident", "technical"],
            prohibited_claims=["indestructible"],
            visual_donts=["never stretch the logo"],
        ),
    )


class TestDiversity:
    def test_three_different_ideas_pass(self) -> None:
        directions = [
            _direction(1),
            _direction(
                2,
                emotional_angle="human aspiration",
                subject="an architect mid-decision",
                environment="an occupied atrium at opening hour",
                composition="wide environmental portrait",
                lighting="soft diffused window light",
                visual_metaphor="a person trusting the structure",
            ),
            _direction(
                3,
                emotional_angle="architectural modernity",
                subject="the elevation read as pure geometry",
                environment="open sky above an urban edge",
                composition="asymmetric diagonal with negative space",
                lighting="flat overcast daylight",
                visual_metaphor="form against horizon",
            ),
        ]
        assert assess_diversity(directions).passed

    def test_the_same_poster_three_times_is_caught(self) -> None:
        """The failure this check exists for: one idea, three backgrounds."""
        directions = [
            _direction(1),
            _direction(2, environment="wet street after monsoon rain at dusk"),
            _direction(3, lighting="directional late afternoon sunlight"),
        ]
        verdict = assess_diversity(directions)
        assert verdict.passed is False
        assert verdict.collisions
        assert verdict.weakest_pair_similarity > SIMILARITY_LIMIT

    def test_the_verdict_names_the_colliding_pair(self) -> None:
        verdict = assess_diversity([_direction(1), _direction(2)])
        assert verdict.collisions[0][:2] == (1, 2)
        assert "too similar" in verdict.describe()

    def test_a_passing_verdict_reads_cleanly(self) -> None:
        verdict = assess_diversity([_direction(1)])
        assert verdict.passed
        assert "meaningfully different" in verdict.describe()

    def test_the_signature_uses_choices_not_prose(self) -> None:
        """Two directions can be worded very differently and still be one idea."""
        reworded = _direction(2, big_idea="Totally different words here entirely")
        assert _direction(1).diversity_signature() == reworded.diversity_signature()


class TestDirectionGeneration:
    async def test_it_produces_three_complete_directions(self) -> None:
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        directions = outcome.direction_set.directions
        assert len(directions) == 3
        for d in directions:
            assert d.title and d.big_idea and d.strategic_rationale
            assert d.emotional_angle and d.key_message and d.audience_connection
            assert d.subject and d.environment and d.composition and d.lighting
            assert d.brand_integration and d.product_integration

    async def test_the_directions_are_meaningfully_different(self) -> None:
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        assert outcome.diversity.passed
        assert len({d.emotional_angle for d in outcome.direction_set.directions}) == 3

    async def test_it_respects_the_campaign_specification(self) -> None:
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        for d in outcome.direction_set.directions:
            assert "FS-9" in d.product_integration or "FS-9" in d.big_idea
            assert d.cta == "Request a specification pack"

    async def test_brand_prohibitions_become_negative_constraints(self) -> None:
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        for d in outcome.direction_set.directions:
            assert "indestructible" in d.negative_constraints.forbidden_text
            assert "never stretch the logo" in d.negative_constraints.forbidden_elements

    async def test_every_direction_states_the_ip_boundary(self) -> None:
        """ADR-011: what is carried forward, and what is deliberately not."""
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        for d in outcome.direction_set.directions:
            assert d.reference_characteristics_used
            assert d.reference_characteristics_avoided

    async def test_a_recommendation_comes_with_readable_reasons(self) -> None:
        outcome = await CreativeDirector(MockLLMProvider()).propose_directions(_context())
        assert outcome.direction_set.recommended_ordinal in (1, 2, 3)
        reasons = outcome.direction_set.recommendation_reasons
        assert reasons
        # A decision summary, never reasoning traces.
        assert all("because I" not in r.lower() for r in reasons)

    async def test_malformed_model_output_raises_rather_than_dropping_fields(self) -> None:
        director = CreativeDirector(MockLLMProvider(failure_mode="malformed"))
        with pytest.raises(ProviderInvalidResponse):
            await director.propose_directions(_context())

    async def test_gaps_are_named_so_the_model_does_not_invent_them(self) -> None:
        context = _context().model_copy(update={"gaps": ["No references analysed."]})
        prompt = build_director_prompt(context)
        assert "do not invent" in prompt.lower()

    async def test_the_prompt_carries_the_context_not_a_rebuild(self) -> None:
        prompt = build_director_prompt(_context())
        assert "FS-9 facade system" in prompt
        assert "Architects in Maharashtra" in prompt
        assert "indestructible" in prompt


class TestSpecification:
    async def test_the_approved_direction_produces_an_execution_plan(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        chosen = outcome.direction_set.directions[0]

        spec = await director.build_specification(_context(), chosen)
        assert spec.direction_id == chosen.id
        assert spec.concept and spec.visual_story and spec.focal_point
        assert spec.people_guidance and spec.headline_guidance and spec.cta_guidance
        assert spec.negative_constraints.no_text_in_image is True

    async def test_a_human_edited_field_survives_regeneration(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        chosen = outcome.direction_set.directions[0]

        first = await director.build_specification(_context(), chosen)
        edited = first.model_copy(
            update={"headline": "A human wrote this", "human_edited_fields": ["headline"]}
        )
        second = await director.build_specification(_context(), chosen, version=2, previous=edited)
        assert second.headline == "A human wrote this"
        assert "headline" in second.human_edited_fields

    async def test_the_specification_never_names_a_font(self) -> None:
        """ADR-011: identified typefaces are exactly what must not transfer."""
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        spec = await director.build_specification(_context(), outcome.direction_set.directions[0])
        assert "font_family" not in CreativeSpecification.model_fields
        assert (
            "typeface" not in (spec.headline_guidance or "").lower()
            or "no typeface" in (spec.headline_guidance or "").lower()
        )


class TestProtectedCampaignFacts:
    """The confirmed campaign facts must survive both model calls.

    The mock deliberately answers the specification call with its own default
    call to action, which is how this catches the real failure: a model that
    reworded the CTA used to have its version accepted, silently editing a
    Campaign Specification a human had already confirmed.
    """

    async def test_every_direction_carries_the_confirmed_call_to_action(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        for direction in outcome.direction_set.directions:
            assert direction.cta == "Request a specification pack"
            assert direction.key_message == "Engineered to outlast the building it clads"

    async def test_the_specification_carries_them_too(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        spec = await director.build_specification(_context(), outcome.direction_set.directions[0])
        assert spec.cta == "Request a specification pack"

    async def test_a_revision_cannot_rewrite_them(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        revision = CreativeRevisionDelta(
            iteration=1,
            feedback="Make the call to action punchier — try 'Get the pack'.",
            keep=list(PROTECTED_CAMPAIGN_FACTS),
            change=["emotional_angle"],
        )
        outcome = await director.propose_directions(_context(), version=2, revision=revision)
        for direction in outcome.direction_set.directions:
            assert direction.cta == "Request a specification pack"

    async def test_the_headline_is_still_the_models_to_write(self) -> None:
        """Pinning facts must not freeze the creative work itself."""
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        headlines = {d.headline for d in outcome.direction_set.directions}
        assert len(headlines) == len(outcome.direction_set.directions)

    async def test_facts_are_left_alone_when_there_is_no_specification(self) -> None:
        """No confirmed specification means nothing to pin to — and no crash."""
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(CreativeContext(campaign_id="c1"))
        assert all(d.cta for d in outcome.direction_set.directions)


class TestTypographyGuidance:
    async def test_the_guidance_is_usable_and_names_no_typeface(self) -> None:
        director = CreativeDirector(MockLLMProvider())
        outcome = await director.propose_directions(_context())
        spec = await director.build_specification(_context(), outcome.direction_set.directions[0])

        guidance = spec.typography_guidance
        assert guidance.headline_treatment and guidance.hierarchy
        words = f"{guidance.headline_treatment} {guidance.hierarchy}".lower()
        for face in ("helvetica", "futura", "gotham", "inter", "roboto", "garamond"):
            assert face not in words


class TestRevisionDelta:
    def test_a_field_cannot_be_both_kept_and_changed(self) -> None:
        with pytest.raises(ValueError, match="both kept and changed"):
            CreativeRevisionDelta(
                iteration=1, feedback="warmer", keep=["product"], change=["product"]
            )

    def test_protected_campaign_facts_are_named(self) -> None:
        """Feedback about tone must not be able to change the product."""
        assert "product" in PROTECTED_CAMPAIGN_FACTS
        assert "audience" in PROTECTED_CAMPAIGN_FACTS
        assert "key_message" in PROTECTED_CAMPAIGN_FACTS

    def test_a_clean_delta_is_accepted(self) -> None:
        delta = CreativeRevisionDelta(
            iteration=1,
            feedback="Too technical, make it aspirational.",
            keep=list(PROTECTED_CAMPAIGN_FACTS),
            change=["emotional_angle", "visual_story"],
        )
        assert delta.keep and delta.change


class TestDirectionSet:
    def test_lookup_by_ordinal_and_id(self) -> None:
        directions = [_direction(1), _direction(2)]
        direction_set = CreativeDirectionSet(campaign_id="c1", directions=directions)
        assert direction_set.by_ordinal(2) is directions[1]
        assert direction_set.by_id(directions[0].id) is directions[0]
        assert direction_set.by_ordinal(9) is None

    def test_an_empty_set_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            CreativeDirectionSet(campaign_id="c1", directions=[])
