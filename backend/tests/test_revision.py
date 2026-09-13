"""The revision loop: delta validation, planning, and deterministic application.

The central promise of Milestone 8 is that feedback *refines* a creative rather
than restarting it. These tests hold that promise to the letter: a delta cannot
reach a locked field uninvited, the planner will not guess at vague feedback,
and applying a delta changes exactly the named fields and nothing else.
"""

from __future__ import annotations

import pytest

from app.domain.campaign import CampaignBrief
from app.domain.common import Channel, StyleFamily
from app.domain.creative import CreativeSpecification, NegativeConstraints
from app.domain.creative_context import BrandGuardrails
from app.domain.revision import (
    IMMUTABLE_FIELDS,
    LOCKED_FIELDS,
    FieldChange,
    RevisionAction,
    RevisionDelta,
)
from app.providers.mock.llm import MockLLMProvider
from app.services.revision_application import (
    RevisionNotApplicable,
    apply_revision,
)
from app.services.revision_planner import (
    REVISABLE_FIELDS,
    FeedbackTooVague,
    RevisionContext,
    RevisionPlanner,
    build_planner_prompt,
    explicit_unlocks,
)

pytestmark = pytest.mark.unit


def _specification(**overrides) -> CreativeSpecification:
    base = {
        "campaign_id": "c1",
        "direction_id": "d1",
        "version": 1,
        "concept": "The facade, read as engineering",
        "visual_story": "A single bay at the hour the light rakes across it",
        "emotional_angle": "engineering confidence",
        "headline": "Built to outlast the building it clads",
        "headline_guidance": "Large, tight leading",
        "cta": "Request the specification pack",
        "cta_guidance": "Lower third, secondary weight",
        "visual_metaphor": "machined precision standing for permanence",
        "composition": "tight orthographic framing",
        "focal_point": "the joint between two panels",
        "subject": "a single bay of the FS-9 facade system",
        "environment": "a modern construction site",
        "lighting": "hard directional studio light",
        "camera": "35mm, eye level",
        "palette": ["#1F2933", "#E4572E"],
        "color_direction": "Restrained ground, one accent",
        "style_families": [StyleFamily.TECHNICAL],
        "mood": ["precise", "quiet"],
        "product_integration": "the system is the subject, not a prop",
        "people_guidance": "no people",
        "brand_integration": "colour and restraint, not a badge",
        "regional_cues": ["Maharashtra monsoon light"],
        "negative_constraints": NegativeConstraints(forbidden_elements=["stock handshakes"]),
        "human_edited_fields": ["headline"],
    }
    return CreativeSpecification(**{**base, **overrides})


def _delta(**overrides) -> RevisionDelta:
    base = {
        "iteration": 1,
        "user_feedback": "Keep everything, but the environment feels generic.",
        "interpretation": "Change the environment only.",
        "keep": ["concept", "headline", "cta", "subject", "composition"],
        "change": [
            FieldChange(
                field="environment",
                reason="needs regional specificity",
                new_value="a completed residential tower in Pune at dusk",
            )
        ],
        "rationale": "Changes only the environment.",
    }
    return RevisionDelta(**{**base, **overrides})


def _context(**overrides) -> RevisionContext:
    base = {
        "specification": _specification(),
        "feedback": "It feels too generic — make the environment more local.",
        "iteration": 1,
        "campaign": CampaignBrief(
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
        "guardrails": BrandGuardrails(prohibited_claims=["indestructible"]),
    }
    return RevisionContext(**{**base, **overrides})


class TestDeltaValidation:
    def test_a_field_cannot_be_both_kept_and_changed(self) -> None:
        with pytest.raises(ValueError, match="both kept and changed"):
            _delta(keep=["environment", "concept"])

    def test_a_field_can_only_be_revised_once(self) -> None:
        """Two instructions for one field have no defined order."""
        with pytest.raises(ValueError, match="only be revised once"):
            _delta(
                change=[
                    FieldChange(field="lighting", reason="a", new_value="softer"),
                    FieldChange(field="lighting", reason="b", new_value="harder"),
                ]
            )

    def test_an_immutable_field_can_never_be_revised(self) -> None:
        for name in ("version", "campaign_id", "direction_id"):
            with pytest.raises(ValueError, match="can never be revised"):
                _delta(change=[FieldChange(field=name, reason="x", new_value="y")])

    def test_a_locked_field_needs_an_explicit_unlock(self) -> None:
        """The heart of "refine, never restart"."""
        with pytest.raises(ValueError, match="locked and were not explicitly unlocked"):
            _delta(
                keep=["concept"],
                change=[FieldChange(field="cta", reason="punchier", new_value="Get the pack")],
            )

    def test_an_unlocked_field_may_be_changed(self) -> None:
        delta = _delta(
            keep=["concept"],
            change=[FieldChange(field="cta", reason="user asked", new_value="Get the pack")],
            explicit_unlocks=["cta"],
        )
        assert delta.touched_fields() == ["cta"]

    def test_a_change_must_carry_a_new_value(self) -> None:
        with pytest.raises(ValueError, match="needs a new value"):
            FieldChange(field="environment", action=RevisionAction.CHANGE, reason="x")

    def test_keep_belongs_in_keep(self) -> None:
        with pytest.raises(ValueError, match="KEEP belongs in"):
            FieldChange(field="environment", action=RevisionAction.KEEP, reason="x")

    def test_an_empty_delta_knows_it_is_empty(self) -> None:
        assert RevisionDelta(iteration=1, user_feedback="hm").is_empty() is True
        assert _delta().is_empty() is False

    def test_the_locked_set_covers_the_approved_facts(self) -> None:
        """These are the fields a human signed off and a drifting model is most
        likely to "improve" uninvited."""
        assert "cta" in LOCKED_FIELDS
        assert "product_integration" in LOCKED_FIELDS
        assert "brand_integration" in LOCKED_FIELDS
        assert "negative_constraints" in LOCKED_FIELDS
        assert "version" in IMMUTABLE_FIELDS


class TestUnlockDetection:
    @pytest.mark.parametrize(
        ("feedback", "expected"),
        [
            ("make the environment more local", []),
            ("the call to action should be punchier", ["cta", "cta_guidance"]),
            ("the product needs to be more prominent", ["product_integration"]),
            ("the brand should be more present", ["brand_integration"]),
        ],
    )
    def test_only_what_the_user_named_is_unlocked(self, feedback, expected) -> None:
        """Decided in code from the user's own words: a model cannot grant
        itself permission by claiming the user meant it."""
        assert explicit_unlocks(feedback) == expected


class TestPlanner:
    async def test_feedback_becomes_a_structured_delta(self) -> None:
        delta = await RevisionPlanner(MockLLMProvider()).plan(_context())
        assert delta.change
        assert delta.keep
        assert delta.rationale
        assert delta.iteration == 1

    async def test_it_changes_only_what_the_feedback_is_about(self) -> None:
        delta = await RevisionPlanner(MockLLMProvider()).plan(
            _context(feedback="Everything is good except the environment — too generic.")
        )
        assert "environment" in delta.touched_fields()
        assert "headline" not in delta.touched_fields()
        assert "cta" not in delta.touched_fields()

    async def test_it_names_what_it_is_preserving(self) -> None:
        """Saying what stays is how a user sees a refinement, not a rewrite."""
        delta = await RevisionPlanner(MockLLMProvider()).plan(_context())
        assert {"concept", "headline", "cta"} <= set(delta.keep)

    async def test_it_never_reaches_a_locked_field_uninvited(self) -> None:
        delta = await RevisionPlanner(MockLLMProvider()).plan(
            _context(feedback="Make the whole thing feel more premium and local.")
        )
        assert not set(delta.touched_fields()) & set(LOCKED_FIELDS)
        assert delta.explicit_unlocks == []

    async def test_vague_feedback_goes_back_to_the_human(self) -> None:
        """A confident revision of something nobody asked for is worse than an
        honest question."""
        with pytest.raises(FeedbackTooVague):
            await RevisionPlanner(MockLLMProvider()).plan(_context(feedback="hmm, not sure"))

    async def test_empty_feedback_is_refused_without_a_model_call(self) -> None:
        class _Exploding:
            name = "exploding"

            async def structured(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError("the planner called the model anyway")

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        with pytest.raises(FeedbackTooVague):
            await RevisionPlanner(_Exploding()).plan(_context(feedback="   "))  # type: ignore[arg-type]

    async def test_it_is_deterministic(self) -> None:
        planner = RevisionPlanner(MockLLMProvider())
        first = await planner.plan(_context())
        second = await planner.plan(_context())
        assert first.touched_fields() == second.touched_fields()

    async def test_an_unknown_field_is_dropped_not_fatal(self) -> None:
        """Three good changes and one invented field should produce three good
        changes."""

        class _Inventive:
            name = "inventive"

            async def structured(self, prompt, schema, **kwargs):
                return schema.model_validate(
                    {
                        "interpretation": "x",
                        "keep": ["concept"],
                        "change": [
                            {"field": "environment", "reason": "r", "new_value": "a new place"},
                            {"field": "vibes", "reason": "r", "new_value": "more vibes"},
                        ],
                        "add": [],
                        "remove": [],
                        "explicit_unlocks": [],
                        "rationale": "r",
                    }
                )

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        delta = await RevisionPlanner(_Inventive()).plan(_context())  # type: ignore[arg-type]
        assert delta.touched_fields() == ["environment"]

    async def test_a_model_cannot_unlock_a_field_by_asking(self) -> None:
        """The unlock is decided from the user's words, not the model's claim."""

        class _Presumptuous:
            name = "presumptuous"

            async def structured(self, prompt, schema, **kwargs):
                return schema.model_validate(
                    {
                        "interpretation": "x",
                        "keep": [],
                        "change": [
                            {"field": "cta", "reason": "better", "new_value": "Buy now"},
                            {"field": "lighting", "reason": "r", "new_value": "softer light"},
                        ],
                        "add": [],
                        "remove": [],
                        "explicit_unlocks": ["cta"],
                        "rationale": "r",
                    }
                )

            async def complete(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError

        delta = await RevisionPlanner(_Presumptuous()).plan(  # type: ignore[arg-type]
            _context(feedback="make the lighting softer")
        )
        assert delta.touched_fields() == ["lighting"]
        assert delta.explicit_unlocks == []

    def test_the_prompt_states_the_locked_fields(self) -> None:
        prompt = build_planner_prompt(_context())
        assert "FIELDS THAT ARE LOCKED" in prompt
        assert "cta" in prompt

    def test_the_prompt_carries_the_approved_campaign_facts(self) -> None:
        prompt = build_planner_prompt(_context())
        assert "these never change here" in prompt
        assert "Get FS-9 onto shortlists" in prompt

    def test_every_revisable_field_exists_on_the_specification(self) -> None:
        """A planner offering a field the model cannot write would produce
        deltas that always fail to apply."""
        for name in REVISABLE_FIELDS:
            assert name in CreativeSpecification.model_fields


class TestApplication:
    def test_only_the_named_field_changes(self) -> None:
        """The central behaviour of Milestone 8, asserted field by field."""
        original = _specification()
        revised, changed = apply_revision(original, _delta())

        assert changed == ["environment"]
        assert revised.environment == "a completed residential tower in Pune at dusk"

        before = original.model_dump(mode="json")
        after = revised.model_dump(mode="json")
        for name in before:
            if name in ("id", "version", "environment", "human_edited_fields", "locked_fields"):
                continue
            assert after[name] == before[name], f"{name} changed and should not have"

    def test_the_previous_version_is_untouched(self) -> None:
        original = _specification()
        snapshot = original.model_dump(mode="json")
        apply_revision(original, _delta())
        assert original.model_dump(mode="json") == snapshot

    def test_the_version_increments_and_the_id_is_new(self) -> None:
        original = _specification(version=3)
        revised, _ = apply_revision(original, _delta())
        assert revised.version == 4
        assert revised.id != original.id

    def test_it_is_deterministic(self) -> None:
        original, delta = _specification(), _delta()
        first, _ = apply_revision(original, delta)
        second, _ = apply_revision(original, delta)
        assert first.model_dump(exclude={"id"}) == second.model_dump(exclude={"id"})

    def test_keep_is_enforced_not_trusted(self) -> None:
        """A delta that promised to keep a field it also rewrites is caught by
        the delta itself; this proves the application checks the real result."""
        original = _specification()
        revised, _ = apply_revision(original, _delta(keep=["headline", "cta", "subject"]))
        assert revised.headline == original.headline
        assert revised.cta == original.cta
        assert revised.subject == original.subject

    def test_a_locked_field_cannot_be_applied_uninvited(self) -> None:
        """The last line of defence, below the delta's own validator."""
        # `model_construct` skips validation, which is how a bad import, a
        # fixture or a future code path could produce a delta the domain model
        # would have refused. The application service must still stop it.
        smuggled = RevisionDelta.model_construct(
            iteration=1,
            user_feedback="x",
            keep=[],
            change=[FieldChange(field="cta", reason="x", new_value="Buy now")],
            add=[],
            remove=[],
            explicit_unlocks=[],
        )
        with pytest.raises(RevisionNotApplicable, match="locked"):
            apply_revision(_specification(), smuggled)

    def test_an_explicitly_unlocked_field_applies(self) -> None:
        revised, changed = apply_revision(
            _specification(),
            _delta(
                keep=["concept"],
                change=[FieldChange(field="cta", reason="user asked", new_value="Get the pack")],
                explicit_unlocks=["cta"],
            ),
        )
        assert revised.cta == "Get the pack"
        assert changed == ["cta"]

    def test_adding_to_a_list_appends(self) -> None:
        revised, changed = apply_revision(
            _specification(),
            _delta(
                keep=["concept"],
                change=[],
                add=[
                    FieldChange(
                        field="mood",
                        action=RevisionAction.ADD,
                        reason="warmer",
                        new_value="optimistic",
                    )
                ],
            ),
        )
        assert revised.mood == ["precise", "quiet", "optimistic"]
        assert changed == ["mood"]

    def test_adding_a_duplicate_is_a_no_op(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="makes no changes"):
            apply_revision(
                _specification(),
                RevisionDelta(
                    iteration=1,
                    user_feedback="x",
                    add=[],
                    change=[],
                ),
            )

    def test_removing_from_a_list_drops_it(self) -> None:
        revised, changed = apply_revision(
            _specification(),
            _delta(
                keep=["concept"],
                change=[],
                remove=[
                    FieldChange(
                        field="mood",
                        action=RevisionAction.REMOVE,
                        reason="too cold",
                        new_value="quiet",
                    )
                ],
            ),
        )
        assert revised.mood == ["precise"]

    def test_removing_an_optional_field_clears_it(self) -> None:
        revised, _ = apply_revision(
            _specification(),
            _delta(
                keep=["concept"],
                change=[],
                remove=[
                    FieldChange(
                        field="camera",
                        action=RevisionAction.REMOVE,
                        reason="let it be free",
                        new_value="35mm, eye level",
                    )
                ],
            ),
        )
        assert revised.camera is None

    def test_a_required_field_cannot_be_removed(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="cannot be removed"):
            apply_revision(
                _specification(),
                _delta(
                    keep=["concept"],
                    change=[],
                    remove=[
                        FieldChange(
                            field="subject",
                            action=RevisionAction.REMOVE,
                            reason="x",
                            new_value="y",
                        )
                    ],
                ),
            )

    def test_adding_to_a_non_list_is_refused(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="not a list"):
            apply_revision(
                _specification(),
                _delta(
                    keep=["concept"],
                    change=[],
                    add=[
                        FieldChange(
                            field="lighting",
                            action=RevisionAction.ADD,
                            reason="x",
                            new_value="more light",
                        )
                    ],
                ),
            )

    def test_a_structured_field_cannot_be_revised_as_prose(self) -> None:
        smuggled = _delta(
            keep=["concept"],
            change=[
                FieldChange(field="negative_constraints", reason="x", new_value="anything goes")
            ],
            explicit_unlocks=["negative_constraints"],
        )
        with pytest.raises(RevisionNotApplicable, match="structured"):
            apply_revision(_specification(), smuggled)

    def test_a_revised_field_stops_being_a_human_edit(self) -> None:
        """A human wrote the old headline; this revision wrote the new one."""
        original = _specification(human_edited_fields=["headline", "subject"])
        revised, _ = apply_revision(
            original,
            _delta(
                keep=["concept"],
                change=[FieldChange(field="headline", reason="x", new_value="A new headline")],
            ),
        )
        assert revised.human_edited_fields == ["subject"]

    def test_an_untouched_human_edit_survives(self) -> None:
        original = _specification(human_edited_fields=["headline"])
        revised, _ = apply_revision(original, _delta())
        assert revised.human_edited_fields == ["headline"]

    def test_an_empty_delta_is_refused(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="makes no changes"):
            apply_revision(_specification(), RevisionDelta(iteration=1, user_feedback="looks fine"))

    def test_several_fields_change_together(self) -> None:
        revised, changed = apply_revision(
            _specification(),
            _delta(
                keep=["concept", "headline", "cta"],
                change=[
                    FieldChange(field="environment", reason="a", new_value="a Pune rooftop"),
                    FieldChange(field="lighting", reason="b", new_value="soft dusk light"),
                ],
            ),
        )
        assert changed == ["environment", "lighting"]
        assert revised.environment == "a Pune rooftop"
        assert revised.lighting == "soft dusk light"
