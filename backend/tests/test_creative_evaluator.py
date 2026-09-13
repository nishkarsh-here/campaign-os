"""The Creative Evaluator service.

What matters here is the boundary between what the model is asked and what the
backend decides: the model scores dimensions and writes one-line notes, and
nothing else. The total, the disposition and every fact already in the database
are settled in code.
"""

from __future__ import annotations

import pytest

from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, StyleFamily
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.evaluation import (
    DIMENSION_WEIGHTS,
    EVALUATOR_VERSION,
    Dimension,
    aggregate_score,
    decide_disposition,
)
from app.domain.generation import AssetKind, GeneratedAsset
from app.domain.reference import AggregateReferenceStyle, Lighting
from app.providers.base import ImageRef, ProviderInvalidResponse, ProviderTimeout
from app.providers.mock.llm import MockLLMProvider
from app.services.creative_evaluator import (
    AssetNotEvaluable,
    CreativeEvaluator,
    EvaluationContext,
    ProposedEvaluation,
    build_evaluation_prompt,
    check_evaluable,
)

pytestmark = pytest.mark.unit


def _asset(**overrides) -> GeneratedAsset:
    base = {
        "id": "asset-1",
        "campaign_id": "c1",
        "generation_job_id": "job-1",
        "prompt_id": "p1",
        "specification_id": "spec-1",
        "specification_version": 3,
        "provider": "mock",
        "model": "mock-image-1",
        "storage_key": "org-x/campaign-y/generated/z.png",
        "width": 1024,
        "height": 1024,
    }
    return GeneratedAsset(**{**base, **overrides})


def _specification(**overrides) -> CreativeSpecification:
    base = {
        "campaign_id": "c1",
        "direction_id": "d1",
        "version": 3,
        "concept": "The facade, read as engineering",
        "visual_story": "A single bay at the hour the light rakes across it",
        "emotional_angle": "engineering confidence",
        "headline": "Built to outlast the building it clads",
        "cta": "Request the specification pack",
        "visual_metaphor": "machined precision standing for permanence",
        "composition": "tight orthographic framing",
        "focal_point": "the joint between two panels",
        "subject": "a single bay of the FS-9 facade system",
        "environment": "a fabrication floor",
        "lighting": "hard directional studio light",
        "color_direction": "Restrained ground, one accent",
        "style_families": [StyleFamily.TECHNICAL],
        "mood": ["precise"],
        "people_guidance": "no people",
        "product_integration": "the system is the subject",
        "brand_integration": "colour and restraint, not a badge",
    }
    return CreativeSpecification(**{**base, **overrides})


def _context(**overrides) -> EvaluationContext:
    base = {
        "asset": _asset(),
        "specification": _specification(),
        "campaign": CampaignBrief(
            campaign_id="c1",
            title="Launch",
            objective="Get FS-9 onto shortlists at design stage",
            audience="Architects and facade consultants in Mumbai",
            product="FS-9 facade system",
            key_message="Built to outlast the building it clads",
            cta="Request the specification pack",
            channels=[Channel.INSTAGRAM_POST],
            region="Maharashtra, India",
        ),
        "guardrails": BrandGuardrails(
            tone_attributes=["confident", "technical"],
            palette=["#1F2933"],
            prohibited_claims=["indestructible"],
            visual_donts=["never stretch the logo"],
        ),
        "reference_style": AggregateReferenceStyle(
            dominant_styles=[StyleFamily.TECHNICAL],
            shared_takeaways=["restrained palette", "generous negative space"],
            common_lighting=Lighting.NATURAL,
            reference_count=2,
        ),
        "brand_name": "Northline",
    }
    return EvaluationContext(**{**base, **overrides})


def _image(payload: bytes = b"plate-one") -> ImageRef:
    return ImageRef(data=payload, mime_type="image/png")


class TestDeterministicPreChecks:
    def test_a_normal_plate_is_evaluable(self) -> None:
        check_evaluable(_asset())

    def test_a_tiny_image_is_not_worth_judging(self) -> None:
        with pytest.raises(AssetNotEvaluable, match="too small"):
            check_evaluable(_asset(width=64, height=64))

    def test_a_non_image_is_rejected(self) -> None:
        with pytest.raises(AssetNotEvaluable, match="not an evaluable image type"):
            check_evaluable(_asset(mime_type="application/pdf"))

    def test_only_plates_are_evaluated(self) -> None:
        with pytest.raises(AssetNotEvaluable, match="Only visual plates"):
            check_evaluable(_asset(kind=AssetKind.FINAL_COMPOSITION))

    async def test_the_model_is_never_called_for_a_failed_pre_check(self) -> None:
        """A fact code can settle must not cost a model call."""

        class _Exploding:
            name = "exploding"

            async def structured(self, *args, **kwargs):  # pragma: no cover - must not run
                raise AssertionError("the evaluator called the model anyway")

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        evaluator = CreativeEvaluator(_Exploding())  # type: ignore[arg-type]
        with pytest.raises(AssetNotEvaluable):
            await evaluator.evaluate(_context(asset=_asset(width=10, height=10)), _image())


class TestThePrompt:
    def test_it_carries_the_approved_plan(self) -> None:
        prompt = build_evaluation_prompt(_context())
        assert "a single bay of the FS-9 facade system" in prompt
        assert "a fabrication floor" in prompt
        assert "hard directional studio light" in prompt

    def test_it_carries_the_campaign_and_brand(self) -> None:
        prompt = build_evaluation_prompt(_context())
        assert "Get FS-9 onto shortlists" in prompt
        assert "Architects and facade consultants" in prompt
        assert "Northline" in prompt
        assert "indestructible" in prompt

    def test_it_names_the_specification_version(self) -> None:
        """An evaluation must be legible as "judged against version N"."""
        assert "version 3" in build_evaluation_prompt(_context())

    def test_it_defines_every_dimension(self) -> None:
        prompt = build_evaluation_prompt(_context())
        for dimension in Dimension:
            assert dimension.value in prompt

    def test_it_states_the_plate_boundary(self) -> None:
        """ADR-006: rendered text is a defect, never a bonus."""
        prompt = build_evaluation_prompt(_context())
        assert "VISUAL PLATE" in prompt
        assert "defect" in prompt

    def test_reference_alignment_is_about_qualities_not_resemblance(self) -> None:
        """The M4 IP boundary, restated where the judgement happens."""
        prompt = build_evaluation_prompt(_context())
        assert "INTENDED STYLE CHARACTERISTICS" in prompt
        assert "Never judge whether it resembles any particular reference" in prompt

    def test_a_missing_region_is_stated_rather_than_guessed(self) -> None:
        campaign = _context().campaign
        assert campaign is not None
        prompt = build_evaluation_prompt(
            _context(campaign=campaign.model_copy(update={"region": None}))
        )
        assert "score regional fit 50" in prompt

    def test_no_references_means_no_style_section(self) -> None:
        prompt = build_evaluation_prompt(_context(reference_style=AggregateReferenceStyle()))
        assert "INTENDED STYLE CHARACTERISTICS" not in prompt

    def test_the_model_is_told_not_to_return_a_verdict(self) -> None:
        from app.services.creative_evaluator import EVALUATOR_SYSTEM

        assert "Do not return an overall score or a verdict" in EVALUATOR_SYSTEM
        assert "Do not suggest rewritten prompts" in EVALUATOR_SYSTEM


class TestTheModelCannotDecide:
    def test_its_schema_has_no_overall_score(self) -> None:
        """Nothing for a model to invent: the total is computed."""
        assert "overall_score" not in ProposedEvaluation.model_fields
        assert "disposition" not in ProposedEvaluation.model_fields

    async def test_the_total_is_computed_from_the_returned_scores(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        assert evaluation.overall_score == aggregate_score(evaluation.score_map())

    async def test_the_disposition_follows_the_thresholds(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        expected, _ = decide_disposition(evaluation.score_map(), evaluation.overall_score)
        assert evaluation.disposition is expected


class TestEvaluating:
    async def test_it_scores_every_dimension(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        assert set(evaluation.score_map()) == set(DIMENSION_WEIGHTS)

    async def test_every_score_carries_a_one_line_note(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        for result in evaluation.dimensions:
            assert result.note
            assert "\n" not in result.note

    async def test_it_records_its_provenance(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        assert evaluation.evaluator_version == EVALUATOR_VERSION
        assert evaluation.evaluator_model == "mock"
        # The plan the asset actually came from, not the latest one.
        assert evaluation.specification_id == "spec-1"
        assert evaluation.specification_version == 3

    async def test_it_summarises_without_reasoning_traces(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        evaluation = await evaluator.evaluate(_context(), _image())
        assert evaluation.rationale
        assert len(evaluation.rationale) < 300
        assert evaluation.strengths and evaluation.concerns

    async def test_the_specification_is_not_mutated(self) -> None:
        """The evaluator assesses; it never edits its subject."""
        specification = _specification()
        before = specification.model_dump(mode="json")
        await CreativeEvaluator(MockLLMProvider()).evaluate(
            _context(specification=specification), _image()
        )
        assert specification.model_dump(mode="json") == before


class TestTheMockIsDeterministicAndDiscriminating:
    async def test_the_same_image_always_scores_the_same(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider())
        first = await evaluator.evaluate(_context(), _image(b"same-plate"))
        second = await evaluator.evaluate(_context(), _image(b"same-plate"))
        assert first.score_map() == second.score_map()
        assert first.overall_score == second.overall_score

    async def test_different_images_score_differently(self) -> None:
        """A mock that returned the same score for everything would make
        ranking untestable."""
        evaluator = CreativeEvaluator(MockLLMProvider())
        scores = set()
        for payload in (b"plate-a", b"plate-b", b"plate-c", b"plate-d"):
            evaluation = await evaluator.evaluate(_context(), _image(payload))
            scores.add(evaluation.overall_score)
        assert len(scores) >= 3

    async def test_a_single_evaluation_is_not_flat(self) -> None:
        """Realistic shape: strong on some dimensions, weak on others — which
        is what the disposition rules exist to handle."""
        evaluation = await CreativeEvaluator(MockLLMProvider()).evaluate(_context(), _image())
        values = list(evaluation.score_map().values())
        assert max(values) - min(values) >= 10

    async def test_a_batch_spans_more_than_one_disposition(self) -> None:
        """The mock has to be able to produce a reject, or the threshold path
        is never exercised end to end offline."""
        evaluator = CreativeEvaluator(MockLLMProvider())
        dispositions = set()
        for index in range(40):
            evaluation = await evaluator.evaluate(_context(), _image(f"plate-{index}".encode()))
            dispositions.add(evaluation.disposition)
        assert len(dispositions) >= 2


class TestFailures:
    async def test_a_provider_timeout_propagates_as_a_typed_error(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider("timeout"))
        with pytest.raises(ProviderTimeout):
            await evaluator.evaluate(_context(), _image())

    async def test_a_malformed_response_is_a_typed_error(self) -> None:
        evaluator = CreativeEvaluator(MockLLMProvider("malformed"))
        with pytest.raises(ProviderInvalidResponse):
            await evaluator.evaluate(_context(), _image())

    async def test_an_empty_dimension_list_is_rejected_by_the_schema(self) -> None:
        with pytest.raises(ValueError):
            ProposedEvaluation(dimensions=[])

    async def test_a_response_with_no_scores_is_an_invalid_response(self) -> None:
        """Defence in depth behind the schema's own `min_length`."""

        class _Empty:
            name = "empty"

            async def structured(self, prompt, schema, **kwargs):
                return schema.model_construct(
                    dimensions=[], strengths=[], concerns=[], rationale=""
                )

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        with pytest.raises(ProviderInvalidResponse):
            await CreativeEvaluator(_Empty()).evaluate(_context(), _image())  # type: ignore[arg-type]

    async def test_a_partial_evaluation_still_produces_a_usable_result(self) -> None:
        """A model that scored six dimensions is reported on what it measured,
        renormalised, rather than being discarded."""

        class _Partial:
            name = "partial"

            async def structured(self, prompt, schema, **kwargs):
                return schema.model_validate(
                    {
                        "dimensions": [
                            {"dimension": "brand_alignment", "score": 90, "note": "on brand"},
                            {"dimension": "visual_quality", "score": 70, "note": "clean"},
                        ],
                        "strengths": ["on brand"],
                        "concerns": [],
                        "rationale": "Partial read.",
                    }
                )

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        evaluation = await CreativeEvaluator(_Partial()).evaluate(_context(), _image())  # type: ignore[arg-type]
        assert len(evaluation.dimensions) == 2
        assert 70 < evaluation.overall_score < 90


class TestTheImageIsActuallyUsed:
    async def test_the_asset_image_is_passed_to_the_model(self) -> None:
        """Evaluation is multimodal through the existing abstraction — there is
        no second mechanism, and no evaluating an image sight unseen."""
        seen: dict[str, object] = {}

        class _Recording:
            name = "recording"

            async def structured(self, prompt, schema, *, images=(), **kwargs):
                seen["images"] = images
                seen["prompt"] = prompt
                return schema.model_validate(
                    {
                        "dimensions": [
                            {"dimension": d.value, "score": 80, "note": "n"} for d in Dimension
                        ],
                        "strengths": [],
                        "concerns": [],
                        "rationale": "ok",
                    }
                )

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        image = _image(b"the-actual-plate")
        await CreativeEvaluator(_Recording()).evaluate(_context(), image)  # type: ignore[arg-type]

        assert seen["images"] == (image,)
        assert isinstance(seen["prompt"], str)
