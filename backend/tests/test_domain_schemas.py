"""Domain schema contracts.

These are the guarantees the rest of the system is allowed to rely on.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.domain import (
    ALLOWED_DECISIONS,
    ApprovalDecision,
    BrandProfile,
    CampaignInputs,
    Channel,
    Decision,
    Gate,
    LayoutSpec,
    RevisionDelta,
)
from app.domain.layout import Anchor, Box, ElementType, LayoutElement, TextStyle
from app.domain.revision import FieldChange

pytestmark = pytest.mark.unit


class TestCanonicalVocabulary:
    def test_campaign_specification_is_the_campaign_brief(self) -> None:
        """The canonical business concept is CAMPAIGN SPECIFICATION; the
        implementation type is `CampaignBrief`. Keeping that mapping executable
        means it cannot quietly stop being true (PRODUCT_SPEC §1a)."""
        from app.domain import CampaignBrief, CampaignSpecification

        assert CampaignSpecification is CampaignBrief

    def test_both_names_are_exported(self) -> None:
        import app.domain as domain

        assert {"CampaignBrief", "CampaignSpecification"} <= set(domain.__all__)


class TestStrictness:
    def test_unknown_fields_are_rejected(self) -> None:
        """A model inventing a field must fail loudly, not be absorbed."""
        with pytest.raises(ValidationError):
            BrandProfile(id="b", organization_id="o", name="X", hallucinated_field="oops")

    def test_domain_models_round_trip_through_json(self, brief) -> None:
        """State is checkpointed as JSON, so every domain object must survive it."""
        restored = type(brief).model_validate(json.loads(brief.model_dump_json()))
        assert restored == brief


class TestCampaignInputs:
    def test_empty_inputs_are_insufficient_and_name_what_is_missing(self) -> None:
        inputs = CampaignInputs()
        assert not inputs.is_sufficient()
        assert set(inputs.missing_required()) == set(CampaignInputs.REQUIRED_FIELDS)

    def test_sufficiency_requires_non_empty_lists_not_just_presence(self) -> None:
        inputs = CampaignInputs(
            campaign_objective="launch",
            target_audience="architects",
            product="FS-9",
            key_message="durable",
            channels=[],
        )
        assert inputs.missing_required() == ["channels"]

        inputs.channels = [Channel.LINKEDIN]
        assert inputs.is_sufficient()

    def test_required_fields_is_not_a_model_field(self) -> None:
        """It is configuration, not data — it must never be serialized or
        offered to a language model as something to fill in."""
        assert "REQUIRED_FIELDS" not in CampaignInputs.model_fields
        assert "REQUIRED_FIELDS" not in CampaignInputs().model_dump()


class TestCampaignBrief:
    def test_brief_requires_at_least_one_channel(self, brief) -> None:
        with pytest.raises(ValidationError):
            brief.model_copy(update={"channels": []}).model_validate(
                brief.model_dump() | {"channels": []}
            )

    def test_whitespace_only_core_field_is_rejected(self, brief) -> None:
        with pytest.raises(ValidationError):
            type(brief).model_validate(brief.model_dump() | {"objective": "   "})


class TestEvaluation:
    def test_evaluation_scoring_lives_in_its_own_suite(self) -> None:
        """Milestone 7 replaced the 0-10 criterion sketch with 0-100 dimensions,
        deterministic aggregation and threshold-driven dispositions. The
        arithmetic, the weights and the tie-breaking are pinned in
        `tests/test_evaluation_domain.py`; this only guards the link."""
        from app.domain.evaluation import DIMENSION_WEIGHTS, Dimension

        assert set(DIMENSION_WEIGHTS) == set(Dimension)
        assert sum(DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)


class TestApprovalGates:
    @pytest.mark.parametrize(
        ("gate", "decision"),
        [(g, d) for g, ds in ALLOWED_DECISIONS.items() for d in ds],
    )
    def test_every_allowed_decision_is_accepted(self, gate: Gate, decision: Decision) -> None:
        assert ApprovalDecision(gate=gate, decision=decision).decision is decision

    @pytest.mark.parametrize(
        ("gate", "decision"),
        [
            (Gate.STRATEGY, Decision.SELECT),
            (Gate.SPECIFICATION, Decision.REJECT),
            (Gate.FINAL, Decision.APPROVE),
        ],
    )
    def test_decision_from_the_wrong_gate_is_rejected(self, gate: Gate, decision: Decision) -> None:
        with pytest.raises(ValidationError):
            ApprovalDecision(gate=gate, decision=decision)


class TestRevisionDelta:
    def test_a_field_cannot_be_both_kept_and_changed(self) -> None:
        """The whole promise of the revision loop is that KEEP means kept."""
        with pytest.raises(ValidationError):
            RevisionDelta(
                iteration=1,
                user_feedback="too generic",
                interpretation="ground it regionally",
                keep=["headline", "product_integration"],
                change=[FieldChange(field="headline", reason="contradiction")],
            )

    def test_a_clean_delta_is_accepted(self) -> None:
        delta = RevisionDelta(
            iteration=1,
            user_feedback="too generic",
            interpretation="ground the environment in a real Maharashtra context",
            keep=["headline", "cta", "product_integration"],
            change=[
                FieldChange(
                    field="environment",
                    reason="needs regional specificity",
                    new_value="a completed residential tower in Pune at dusk",
                )
            ],
        )
        assert delta.keep and delta.change

    def test_a_change_must_say_what_to_change_it_to(self) -> None:
        """Milestone 8 applies deltas deterministically, so "regenerate this
        field" is not an instruction — it is a gap the application service
        would have to guess at."""
        with pytest.raises(ValidationError):
            FieldChange(field="environment", reason="too generic")


class TestLayout:
    def test_channel_factory_uses_the_canonical_dimensions(self) -> None:
        spec = LayoutSpec.for_channel("camp-1", Channel.INSTAGRAM_STORY)
        assert (spec.width, spec.height) == (1080, 1920)

    def test_element_must_stay_inside_the_canvas(self) -> None:
        with pytest.raises(ValidationError):
            Box(x=0.8, y=0.1, width=0.5, height=0.2)

    def test_text_element_requires_content(self) -> None:
        with pytest.raises(ValidationError):
            LayoutElement(type=ElementType.TEXT, box=Box(x=0, y=0, width=0.5, height=0.1))

    def test_logo_element_requires_a_storage_key(self) -> None:
        with pytest.raises(ValidationError):
            LayoutElement(type=ElementType.LOGO, box=Box(x=0, y=0, width=0.2, height=0.1))

    def test_elements_render_in_z_order_and_skip_hidden(self) -> None:
        box = Box(x=0.1, y=0.1, width=0.3, height=0.1, anchor=Anchor.TOP_LEFT)
        spec = LayoutSpec.for_channel("camp-1", Channel.INSTAGRAM_POST)
        spec.elements = [
            LayoutElement(
                type=ElementType.TEXT, box=box, content="front", z=5, text_style=TextStyle()
            ),
            LayoutElement(type=ElementType.SHAPE, box=box, fill="#000000", z=1),
            LayoutElement(
                type=ElementType.TEXT,
                box=box,
                content="hidden",
                z=9,
                visible=False,
                text_style=TextStyle(),
            ),
        ]
        assert [e.z for e in spec.ordered()] == [1, 5]

    def test_invalid_hex_colour_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TextStyle(color="not-a-colour")


class TestCreativeSpecification:
    def test_text_in_image_is_disabled_by_default(self, specification) -> None:
        """ADR-006: brand text is composed deterministically, never generated."""
        assert specification.negative_constraints.no_text_in_image is True
