"""Per-channel creative copy (Milestone 11).

A campaign is one plan expressed differently per channel. Before M11 it was one
plan expressed *identically* per channel and resized — a 1080x1920 story got a
headline written for a square.

The whole feature is one optional map and one resolver, so the tests that
matter are about what must *not* change:

* a specification with no overrides resolves and renders exactly as it always
  did — the backward-compatibility promise, asserted on real bytes
* an override on one channel touches nothing else
* an override is only approved copy once Gate 2 says so, and the composition
  guard checks against the channel's own approved words rather than the default

The Gate 2 and channel-declaration halves live in
`tests/integration/test_channel_copy_flow.py`, where a campaign exists.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.domain.common import Channel
from app.domain.creative import (
    ChannelCopy,
    CreativeSpecification,
    ResolvedCopy,
    copy_for,
)
from app.domain.revision import FieldChange, RevisionAction, RevisionDelta, locked_leaf
from app.services.brand_guardian import _specification_text
from app.services.layout_builder import adapt_to_channel, build_layout
from app.services.renderer import RenderInputs, render
from app.services.revision_application import (
    RevisionNotApplicable,
    apply_revision,
    parse_channel_copy_field,
)
from tests.test_composition import _guardrails, _logo, _plate, _specification

pytestmark = pytest.mark.unit

STORY = Channel.INSTAGRAM_STORY
POST = Channel.INSTAGRAM_POST
LINKEDIN = Channel.LINKEDIN


def _layout_for(channel: Channel, specification: CreativeSpecification):
    return build_layout(
        campaign_id="c1",
        channel=channel,
        specification=specification,
        guardrails=_guardrails(),
        plate_storage_key="org/campaign/plate.png",
        logo_storage_key="org/brand/logo.png",
        source_asset_id="asset-1",
    )


def _text(layout, role: str) -> str | None:
    element = layout.by_role(role)
    return element.content if element else None


def _delta(**kwargs) -> RevisionDelta:
    return RevisionDelta(iteration=1, user_feedback="feedback", **kwargs)


def _change(field: str, value: str) -> FieldChange:
    return FieldChange(
        field=field, action=RevisionAction.CHANGE, reason="Addresses the feedback.", new_value=value
    )


# ===========================================================================
class TestNothingChangesWithoutAnOverride:
    """Acceptance criterion 1. The backward-compatibility promise.

    Every specification written before M11 has no `channel_copy` at all, so
    "absent" and "empty" and "an override for a different channel" must all
    resolve to the same words and the same pixels.
    """

    def test_a_specification_with_no_overrides_resolves_to_its_defaults(self) -> None:
        spec = _specification()
        for channel in Channel:
            resolved = copy_for(spec, channel)
            assert resolved.headline == spec.headline
            assert resolved.subhead == spec.subhead
            assert resolved.cta == spec.cta

    def test_a_payload_written_before_the_field_existed_still_validates(self) -> None:
        """The migration-free part of the promise: no stored row needs touching."""
        payload = _specification().model_dump(mode="json")
        del payload["channel_copy"]

        reloaded = CreativeSpecification.model_validate(payload)

        assert reloaded.channel_copy == {}
        assert copy_for(reloaded, STORY).headline == reloaded.headline

    def test_the_rendered_bytes_are_identical(self) -> None:
        """Asserted on pixels, not on the layout object.

        The resolver sits between the specification and the renderer, and a
        difference of one character in the headline changes the wrap, the
        shrink loop and therefore the bytes. Identical bytes is the only
        assertion that covers all of that at once.
        """
        inputs = RenderInputs(plate=_plate(), logo=_logo())
        without = render(_layout_for(POST, _specification()), inputs)
        with_empty = render(_layout_for(POST, _specification(channel_copy={})), inputs)

        assert without.data == with_empty.data

    def test_an_override_on_another_channel_changes_nothing_here(self) -> None:
        inputs = RenderInputs(plate=_plate(), logo=_logo())
        plain = render(_layout_for(POST, _specification()), inputs)
        elsewhere = _specification(
            channel_copy={STORY: ChannelCopy(headline="Outlasts the building")}
        )

        assert render(_layout_for(POST, elsewhere), inputs).data == plain.data


class TestAnOverrideChangesOnlyItsChannel:
    """Acceptance criterion 2."""

    def test_the_overridden_channel_uses_its_own_words(self) -> None:
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Outlasts the building")})

        assert _text(_layout_for(STORY, spec), "headline") == "Outlasts the building"

    def test_every_other_channel_keeps_the_default(self) -> None:
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Outlasts the building")})

        for channel in (POST, LINKEDIN, Channel.FACEBOOK):
            assert _text(_layout_for(channel, spec), "headline") == spec.headline

    def test_a_partial_override_inherits_the_rest(self) -> None:
        """An override is a sparse diff, not a second plan."""
        spec = _specification(channel_copy={LINKEDIN: ChannelCopy(headline="Specified to last")})

        resolved = copy_for(spec, LINKEDIN)

        assert resolved.headline == "Specified to last"
        assert resolved.cta == spec.cta, "an unset leaf falls back"
        assert resolved.subhead == spec.subhead

    def test_each_channel_can_carry_its_own_override(self) -> None:
        spec = _specification(
            channel_copy={
                STORY: ChannelCopy(headline="Outlasts the building"),
                LINKEDIN: ChannelCopy(headline="Specified to last", cta="Talk to our team"),
            }
        )

        assert copy_for(spec, STORY).headline == "Outlasts the building"
        assert copy_for(spec, STORY).cta == spec.cta
        assert copy_for(spec, LINKEDIN).cta == "Talk to our team"
        assert copy_for(spec, POST).headline == spec.headline


class TestChannelVariantsCarryTheirOwnCopy:
    """A variant is a re-layout, and after M11 the copy is the one thing that
    may differ between the source and the target."""

    def test_a_variant_picks_up_the_target_channels_words(self) -> None:
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Outlasts the building")})
        base = _layout_for(POST, spec)

        variant = adapt_to_channel(base, STORY, specification=spec)

        assert _text(variant, "headline") == "Outlasts the building"
        assert _text(base, "headline") == spec.headline, "the source is not mutated"

    def test_without_a_specification_it_is_a_pure_re_layout(self) -> None:
        """The pre-M11 signature still means exactly what it meant."""
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Outlasts the building")})
        base = _layout_for(POST, spec)

        variant = adapt_to_channel(base, STORY)

        assert _text(variant, "headline") == spec.headline

    def test_a_variant_never_invents_a_subhead_element(self) -> None:
        """A re-layout moves what is there. If the source dropped the subhead,
        an override cannot bring it back — reserving space for an element that
        does not exist would leave a gap nothing fills."""
        spec = _specification(channel_copy={STORY: ChannelCopy(subhead="Tested to 2,400 Pa")})
        wide = _layout_for(LINKEDIN, spec)
        assert wide.by_role("subhead") is None, "the banner drops the subhead"

        variant = adapt_to_channel(wide, STORY, specification=spec)

        assert variant.by_role("subhead") is None

    def test_every_variant_still_renders(self) -> None:
        spec = _specification(
            channel_copy={
                STORY: ChannelCopy(headline="Outlasts the building"),
                LINKEDIN: ChannelCopy(headline="Specified to last", cta="Talk to our team"),
            }
        )
        base = _layout_for(POST, spec)
        inputs = RenderInputs(plate=_plate(), logo=_logo())

        for channel in (STORY, LINKEDIN, Channel.FACEBOOK):
            result = render(adapt_to_channel(base, channel, specification=spec), inputs)
            with Image.open(io.BytesIO(result.data)) as image:
                assert image.size == (result.width, result.height)


class TestASingleChannelRevision:
    """Acceptance criterion 5, at the pure-function layer.

    `apply_revision` is where "refine, never restart" is actually enforced, so
    it is where per-channel copy has to prove it does not spill.
    """

    def test_one_channels_headline_moves_and_nothing_else_does(self) -> None:
        spec = _specification(channel_copy={LINKEDIN: ChannelCopy(headline="Specified to last")})

        revised, _ = apply_revision(
            spec, _delta(change=[_change("channel_copy.instagram_story.headline", "Outlasts it")])
        )

        assert copy_for(revised, STORY).headline == "Outlasts it"
        assert copy_for(revised, LINKEDIN).headline == "Specified to last", "other override kept"
        assert copy_for(revised, POST).headline == spec.headline, "default untouched"
        assert revised.headline == spec.headline

    def test_v1_is_untouched(self) -> None:
        spec = _specification()
        before = spec.model_dump(mode="json")

        revised, _ = apply_revision(
            spec, _delta(change=[_change("channel_copy.instagram_story.headline", "Outlasts it")])
        )

        assert spec.model_dump(mode="json") == before
        assert spec.channel_copy == {}
        assert revised.version == spec.version + 1
        assert revised.id != spec.id

    def test_removing_an_override_returns_the_channel_to_the_default(self) -> None:
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Outlasts it")})

        revised, _ = apply_revision(
            spec,
            _delta(
                remove=[
                    FieldChange(
                        field="channel_copy.instagram_story.headline",
                        action=RevisionAction.REMOVE,
                        reason="Back to the campaign line.",
                    )
                ]
            ),
        )

        assert copy_for(revised, STORY).headline == spec.headline
        assert STORY not in revised.channel_copy, "an empty override is dropped, not kept empty"

    def test_a_per_channel_cta_is_locked_like_the_default_one(self) -> None:
        """The rule that would have been easiest to miss.

        A call to action is an approved campaign fact whether it is the default
        or one channel's own, and matching the whole field name would have let
        `channel_copy.linkedin.cta` walk straight past the lock.
        """
        assert locked_leaf("channel_copy.linkedin.cta")
        assert locked_leaf("cta")
        assert not locked_leaf("channel_copy.linkedin.headline")

        with pytest.raises(ValueError, match="locked"):
            _delta(change=[_change("channel_copy.linkedin.cta", "Buy now")])

    def test_an_explicit_unlock_still_works_per_channel(self) -> None:
        spec = _specification()

        revised, _ = apply_revision(
            spec,
            _delta(
                explicit_unlocks=["channel_copy.linkedin.cta"],
                change=[_change("channel_copy.linkedin.cta", "Talk to our facade team")],
            ),
        )

        assert copy_for(revised, LINKEDIN).cta == "Talk to our facade team"
        assert copy_for(revised, POST).cta == spec.cta

    def test_the_whole_map_cannot_be_revised_as_prose(self) -> None:
        """A structured field is changed by the service that owns it, not by a
        model writing a sentence into it."""
        with pytest.raises(RevisionNotApplicable, match="one channel at a time"):
            apply_revision(_specification(), _delta(change=[_change("channel_copy", "something")]))

    def test_an_unknown_channel_is_refused(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="not a channel"):
            parse_channel_copy_field("channel_copy.tiktok.headline")

    def test_an_unknown_leaf_is_refused(self) -> None:
        with pytest.raises(RevisionNotApplicable, match="not per-channel copy"):
            parse_channel_copy_field("channel_copy.linkedin.subject")

    def test_an_ordinary_field_is_not_mistaken_for_one(self) -> None:
        assert parse_channel_copy_field("headline") is None
        assert parse_channel_copy_field("channel_copy") is None


class TestOverridesAreCheckedForBrandSafety:
    """Not in the milestone's list, and it would have been a real hole.

    The Guardian's claim check scans the approved plan's prose. An override is
    approved copy that reaches a deliverable, so a prohibited claim placed in
    one would have shipped through the one channel nobody scanned.
    """

    def test_override_text_reaches_the_claim_scanner(self) -> None:
        spec = _specification(channel_copy={STORY: ChannelCopy(headline="Indestructible cladding")})

        assert "Indestructible cladding" in _specification_text(spec)

    def test_the_default_text_is_still_scanned(self) -> None:
        spec = _specification()
        text = _specification_text(spec)

        assert spec.headline in text and spec.cta in text


class TestTheResolverIsTheOnlyRule:
    def test_resolved_copy_always_has_a_headline_and_a_cta(self) -> None:
        """`ChannelCopy` is a sparse diff where None means inherit; the
        resolved answer is complete. Collapsing the two types would make
        "not overridden" and "no headline" the same value."""
        resolved = copy_for(_specification(), POST)

        assert isinstance(resolved, ResolvedCopy)
        assert resolved.headline and resolved.cta

    def test_an_empty_override_is_recognisable(self) -> None:
        assert ChannelCopy().is_empty()
        assert not ChannelCopy(headline="x").is_empty()
