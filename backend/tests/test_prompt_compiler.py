"""The Prompt Compiler and the provider adapters.

The properties under test are the ones the architecture rests on: compilation
is deterministic, it never edits its source, brand text never reaches the image
model, and an adapter changes formatting rather than meaning.
"""

from __future__ import annotations

import pytest

from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, StyleFamily
from app.domain.creative import CreativeSpecification, NegativeConstraints, TypographyGuidance
from app.domain.creative_context import BrandGuardrails, CreativeContext
from app.domain.prompt import CanonicalPrompt, nearest_aspect_ratio
from app.domain.reference import AggregateReferenceStyle, Lighting, ReferenceAnalysis
from app.providers.gemini.prompt import GeminiPromptAdapter
from app.providers.leonardo.prompt import LeonardoPromptAdapter
from app.providers.mock.prompt import MockPromptAdapter
from app.services.prompt_compiler import (
    SUPPORTED_RATIOS,
    PromptCompiler,
    aspect_ratio_for,
    text_safe_area_for,
)

pytestmark = pytest.mark.unit


def _specification(**overrides) -> CreativeSpecification:
    base = {
        "campaign_id": "c1",
        "direction_id": "d1",
        "version": 3,
        "concept": "The facade, read as engineering",
        "visual_story": "A single bay at the hour the light rakes across it",
        "emotional_angle": "engineering confidence",
        "headline": "Built to outlast the building it clads",
        "headline_guidance": "Large, tight leading, sentence case",
        "cta": "Request the specification pack",
        "cta_guidance": "Lower third, secondary weight",
        "visual_metaphor": "machined precision standing for permanence",
        "composition": "tight orthographic framing, product filling the frame",
        "focal_point": "the joint between two panels",
        "subject": "a single bay of the FS-9 facade system",
        "environment": "a fabrication floor, machined surfaces",
        "lighting": "hard directional studio light",
        "camera": "35mm, eye level, shallow depth",
        "palette": ["#1F2933", "#E4572E"],
        "color_direction": "Restrained ground, one accent",
        "style_families": [StyleFamily.TECHNICAL],
        "mood": ["precise", "quiet"],
        "typography_guidance": TypographyGuidance(
            headline_treatment="Large, high contrast", hierarchy="Headline, then CTA"
        ),
        "product_integration": "the system is the subject, not a prop",
        "people_guidance": "no people",
        "brand_integration": "colour and restraint, not a badge",
        "regional_cues": ["Maharashtra monsoon light"],
        "negative_constraints": NegativeConstraints(
            forbidden_elements=["stock-photo handshakes"],
            forbidden_text=["indestructible"],
            avoid_styles=["festive"],
        ),
    }
    return CreativeSpecification(**{**base, **overrides})


def _context(**overrides) -> CreativeContext:
    base = {
        "campaign_id": "c1",
        "specification": CampaignBrief(
            campaign_id="c1",
            title="Launch",
            objective="Get FS-9 onto shortlists",
            audience="Architects in Maharashtra",
            product="FS-9 facade system",
            key_message="Built to outlast the building it clads",
            cta="Request the specification pack",
            channels=[Channel.INSTAGRAM_POST],
            region="Maharashtra, India",
        ),
        "guardrails": BrandGuardrails(
            prohibited_claims=["indestructible", "cheapest"],
            visual_donts=["never stretch the logo"],
        ),
        "reference_style": AggregateReferenceStyle(
            shared_takeaways=["restrained palette", "generous negative space"],
            common_lighting=Lighting.NATURAL,
            reference_count=2,
        ),
    }
    return CreativeContext(**{**base, **overrides})


class TestDeterminism:
    def test_compiling_twice_gives_the_same_prompt(self) -> None:
        """A prompt that changed between compiles could not be reproduced from
        its specification, which is the traceability M6 promises."""
        compiler = PromptCompiler()
        spec, context = _specification(), _context()

        first = compiler.compile(spec, context=context)
        second = compiler.compile(spec, context=context)

        assert first.source_fingerprint == second.source_fingerprint
        assert first.render() == second.render()
        assert first.negative_text() == second.negative_text()

    def test_a_changed_specification_changes_the_fingerprint(self) -> None:
        compiler = PromptCompiler()
        first = compiler.compile(_specification())
        second = compiler.compile(_specification(lighting="soft overcast daylight"))
        assert first.source_fingerprint != second.source_fingerprint

    def test_an_untouched_field_does_not_change_the_fingerprint(self) -> None:
        """`headline` is not compiled into the plate — the deterministic
        renderer sets it — so changing it must not invalidate the prompt."""
        compiler = PromptCompiler()
        first = compiler.compile(_specification())
        second = compiler.compile(_specification(headline="A different headline"))
        assert first.source_fingerprint == second.source_fingerprint


class TestCompleteness:
    def test_every_control_survives_compilation(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())

        assert canonical.subject == "a single bay of the FS-9 facade system"
        assert canonical.environment == "a fabrication floor, machined surfaces"
        assert canonical.visual_story
        assert canonical.composition
        assert canonical.focal_point == "the joint between two panels"
        assert canonical.camera == "35mm, eye level, shallow depth"
        assert canonical.lighting == "hard directional studio light"
        assert canonical.color_direction
        assert canonical.palette == ["#1F2933", "#E4572E"]
        assert canonical.mood == ["precise", "quiet"]
        assert canonical.product_integration
        assert canonical.people_guidance == "no people"
        assert canonical.brand_integration
        assert canonical.typography_guidance.headline_treatment
        assert canonical.regional_cues == ["Maharashtra monsoon light"]

    def test_the_rendering_mentions_every_populated_control(self) -> None:
        text = PromptCompiler().compile(_specification(), context=_context()).render()
        for fragment in (
            "a single bay of the FS-9 facade system",
            "a fabrication floor",
            "the joint between two panels",
            "hard directional studio light",
            "#1F2933",
            "precise",
            "no people",
            "Maharashtra monsoon light",
        ):
            assert fragment in text

    def test_it_carries_the_specification_version(self) -> None:
        canonical = PromptCompiler().compile(_specification(version=7))
        assert canonical.specification_version == 7


class TestNegativeConstraints:
    def test_the_specifications_constraints_are_preserved(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        negative = canonical.negative_text()
        assert "stock-photo handshakes" in negative
        assert "indestructible" in negative
        assert "festive" in negative

    def test_brand_prohibitions_are_added(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        assert "cheapest" in canonical.negative_text()
        assert "never stretch the logo" in canonical.negative_constraints.forbidden_elements

    def test_no_text_in_image_cannot_be_switched_off(self) -> None:
        """ADR-006. A plate carrying its own headline is the wrong renderer
        doing the job, so no upstream field may allow it."""
        permissive = _specification(
            negative_constraints=NegativeConstraints(no_text_in_image=False)
        )
        canonical = PromptCompiler().compile(permissive)
        assert canonical.negative_constraints.no_text_in_image is True
        assert "any text" in canonical.negative_text()

    def test_the_ip_boundary_reaches_the_prompt(self) -> None:
        """The same items `forbids_reproduction()` names, stated to the model."""
        canonical = PromptCompiler().compile(_specification(), context=_context())
        forbidden = canonical.negative_constraints.forbidden_elements
        for rule in ReferenceAnalysis.forbids_reproduction():
            assert rule in forbidden


class TestTheImageModelNeverSetsType:
    def test_the_headline_text_is_not_in_the_prompt(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        rendered = f"{canonical.render()} {canonical.negative_text()}"
        assert "Built to outlast the building it clads" not in rendered

    def test_the_cta_text_is_not_in_the_prompt(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        assert "Request the specification pack" not in canonical.render()

    def test_typography_becomes_a_request_for_quiet_space(self) -> None:
        canonical = PromptCompiler().compile(_specification())
        assert canonical.text_safe_area
        assert "composited later" in canonical.text_safe_area


class TestReferenceBoundary:
    def test_only_abstract_qualities_are_carried(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        assert "restrained palette" in canonical.reference_characteristics
        assert any("light" in q for q in canonical.reference_characteristics)

    def test_no_references_means_no_characteristics(self) -> None:
        canonical = PromptCompiler().compile(_specification())
        assert canonical.reference_characteristics == []


class TestAspectRatio:
    def test_the_channel_decides_the_frame(self) -> None:
        square = PromptCompiler().compile(_specification(), context=_context())
        assert square.aspect_ratio == "1:1"

        story_context = _context(
            specification=_context().specification.model_copy(
                update={"channels": [Channel.INSTAGRAM_STORY]}
            )
        )
        tall = PromptCompiler().compile(_specification(), context=story_context)
        assert tall.aspect_ratio == "9:16"

    def test_ratios_come_from_the_channel_dimensions(self) -> None:
        """Derived, not tabulated — a second table could disagree with the
        layout engine's pixels."""
        assert aspect_ratio_for(Channel.INSTAGRAM_POST) == "1:1"
        assert aspect_ratio_for(Channel.INSTAGRAM_STORY) == "9:16"
        assert aspect_ratio_for(Channel.PRINT_A4) == "3:4"

    def test_an_unsupported_ratio_snaps_to_the_nearest(self) -> None:
        assert nearest_aspect_ratio("21:9", ("1:1", "16:9")) == "16:9"
        assert nearest_aspect_ratio("1:1", ("1:1", "16:9")) == "1:1"

    def test_a_malformed_ratio_does_not_raise(self) -> None:
        assert nearest_aspect_ratio("nonsense", ("1:1", "16:9")) == "1:1"


class TestAdaptersFormatRatherThanChange:
    def test_each_adapter_produces_a_valid_model_prompt(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        for adapter in (
            MockPromptAdapter(),
            GeminiPromptAdapter("gemini-2.5-flash-image"),
            LeonardoPromptAdapter("leonardo-phoenix"),
        ):
            prompt = adapter.compile(canonical)
            assert prompt.provider == adapter.name
            assert prompt.model == adapter.model
            assert prompt.text.strip()
            assert prompt.canonical_prompt_id == canonical.id
            assert prompt.specification_id == canonical.specification_id
            assert prompt.specification_version == canonical.specification_version
            assert prompt.aspect_ratio in adapter.supported_aspect_ratios

    def test_adapters_differ_in_wording(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        gemini = GeminiPromptAdapter("gemini-2.5-flash-image").compile(canonical)
        leonardo = LeonardoPromptAdapter("leonardo-phoenix").compile(canonical)
        assert gemini.text != leonardo.text

    def test_but_they_carry_the_same_subject_and_constraints(self) -> None:
        """Formatting may differ; meaning may not."""
        canonical = PromptCompiler().compile(_specification(), context=_context())
        gemini = GeminiPromptAdapter("gemini-2.5-flash-image").compile(canonical)
        leonardo = LeonardoPromptAdapter("leonardo-phoenix").compile(canonical)

        for prompt in (gemini, leonardo):
            assert "a single bay of the FS-9 facade system" in prompt.text
            assert "a fabrication floor" in prompt.text
            assert prompt.negative_text is not None
            assert "any text" in prompt.negative_text

    def test_gemini_folds_the_exclusions_into_the_instruction(self) -> None:
        """Gemini has no negative-prompt field, so they must travel in the text
        — and the adapter is the only place that knows it."""
        canonical = PromptCompiler().compile(_specification(), context=_context())
        gemini = GeminiPromptAdapter("gemini-2.5-flash-image").compile(canonical)
        assert "Do not include:" in gemini.text
        assert "any text" in gemini.text

    def test_leonardo_keeps_them_out_of_the_prompt(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        leonardo = LeonardoPromptAdapter("leonardo-phoenix").compile(canonical)
        assert "Do not include:" not in leonardo.text
        assert leonardo.negative_text and "any text" in leonardo.negative_text

    def test_compiling_does_not_mutate_the_specification(self) -> None:
        """The source of truth is read, never written."""
        spec = _specification()
        before = spec.model_dump(mode="json")

        canonical = PromptCompiler().compile(spec, context=_context())
        for adapter in (
            GeminiPromptAdapter("gemini-2.5-flash-image"),
            LeonardoPromptAdapter("leonardo-phoenix"),
        ):
            adapter.compile(canonical)

        assert spec.model_dump(mode="json") == before

    def test_an_adapter_is_pure(self) -> None:
        canonical = PromptCompiler().compile(_specification(), context=_context())
        adapter = GeminiPromptAdapter("gemini-2.5-flash-image")
        assert adapter.compile(canonical).text == adapter.compile(canonical).text

    def test_a_human_edited_specification_value_reaches_the_prompt_verbatim(self) -> None:
        edited = _specification(
            subject="a human wrote this subject", human_edited_fields=["subject"]
        )
        canonical = PromptCompiler().compile(edited)
        for adapter in (
            MockPromptAdapter(),
            GeminiPromptAdapter("gemini-2.5-flash-image"),
            LeonardoPromptAdapter("leonardo-phoenix"),
        ):
            assert "a human wrote this subject" in adapter.compile(canonical).text


class TestTraceability:
    def test_a_prompt_names_everything_it_descends_from(self) -> None:
        canonical = PromptCompiler().compile(_specification(version=4))
        prompt = GeminiPromptAdapter("gemini-2.5-flash-image").compile(canonical, version=2)
        trace = prompt.trace()
        assert "v4" in trace
        assert "gemini/gemini-2.5-flash-image" in trace
        assert "prompt v2" in trace

    def test_a_canonical_prompt_is_strict(self) -> None:
        with pytest.raises(ValueError):
            CanonicalPrompt(
                campaign_id="c1",
                specification_id="s1",
                subject="x",
                environment="y",
                composition="z",
                lighting="l",
                invented_field="nope",
            )


class TestTheInstagramPortraitChannelCompiles:
    """4:5 has to survive the whole compile, not just exist in the enum.

    The ratio reaches the image provider and the text-safe-area guidance has
    to be the portrait one — a plate told to keep its *left* third quiet is
    useless to a layout that puts type across the bottom.
    """

    def test_the_generation_ratio_is_four_by_five(self) -> None:
        assert aspect_ratio_for(Channel.INSTAGRAM_PORTRAIT) == "4:5"

    def test_it_is_not_snapped_to_another_ratio(self) -> None:
        """Before 4:5 was a supported ratio this snapped to 3:4, which is a
        different frame and a different crop."""
        assert "4:5" in SUPPORTED_RATIOS
        assert aspect_ratio_for(Channel.INSTAGRAM_PORTRAIT) != aspect_ratio_for(
            Channel.INSTAGRAM_POST
        )

    def test_the_quiet_region_is_the_lower_third(self) -> None:
        guidance = text_safe_area_for("4:5")
        assert "lower third" in guidance
        assert "left third" not in guidance
        assert "No lettering" in guidance

    def test_every_supported_ratio_has_quiet_region_guidance(self) -> None:
        """A ratio with no guidance silently falls back to the default, which
        is wrong for a portrait frame."""
        from app.services.prompt_compiler import _QUIET_REGIONS

        for ratio in SUPPORTED_RATIOS:
            assert ratio in _QUIET_REGIONS, ratio

    def test_the_gemini_adapter_accepts_it(self) -> None:
        """The ratio has to be one the image provider will take."""
        from app.providers.gemini.prompt import GEMINI_ASPECT_RATIOS

        assert aspect_ratio_for(Channel.INSTAGRAM_PORTRAIT) in GEMINI_ASPECT_RATIOS

    def test_existing_channel_ratios_are_unchanged(self) -> None:
        assert aspect_ratio_for(Channel.INSTAGRAM_POST) == "1:1"
        assert aspect_ratio_for(Channel.INSTAGRAM_STORY) == "9:16"
        assert aspect_ratio_for(Channel.LINKEDIN) == "16:9"
        assert aspect_ratio_for(Channel.WEB_BANNER) == "16:9"
