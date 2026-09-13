"""Layout validation, the deterministic renderer, and channel adaptation.

The guarantee this milestone rests on is that rendering is a pure function:
the same layout and the same assets produce the same pixels, on any machine.
These tests hold it to that, and to the promise that a poster is never shipped
with type running off the edge.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.domain.common import CHANNEL_DIMENSIONS, Channel
from app.domain.creative import CreativeSpecification
from app.domain.creative_context import BrandGuardrails
from app.domain.layout import (
    PROTECTED_ROLES,
    RENDERER_VERSION,
    Anchor,
    Box,
    ElementType,
    LayoutElement,
    LayoutSpec,
    LayoutVerdict,
    SafeArea,
    TextStyle,
    _bounds,
    validate_layout,
)
from app.services.composition_stage import COMPOSABLE_CHANNELS
from app.services.layout_builder import SAFE_AREAS, adapt_to_channel, build_layout
from app.services.renderer import MIN_SCALE, RenderError, RenderInputs, render

pytestmark = pytest.mark.unit


def _plate(width: int = 1200, height: int = 1200, colour=(40, 60, 80)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _logo(width: int = 240, height: int = 80) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (255, 255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _specification(**overrides) -> CreativeSpecification:
    base = {
        "campaign_id": "c1",
        "direction_id": "d1",
        "version": 2,
        "concept": "The facade, read as engineering",
        "emotional_angle": "engineering confidence",
        "headline": "Built to outlast the building it clads",
        "subhead": "FS-9 engineered facade systems",
        "cta": "Request the specification pack",
        "visual_metaphor": "machined precision",
        "composition": "tight orthographic framing",
        "subject": "a single bay",
        "environment": "a fabrication floor",
        "lighting": "hard directional light",
        "product_integration": "the system is the subject",
        "brand_integration": "colour and restraint",
    }
    return CreativeSpecification(**{**base, **overrides})


def _guardrails(**overrides) -> BrandGuardrails:
    base = {"palette": ["#1F2933", "#E4572E"], "legal_line": "© Northline 2026"}
    return BrandGuardrails(**{**base, **overrides})


def _layout(channel: Channel = Channel.INSTAGRAM_POST, **overrides) -> LayoutSpec:
    return build_layout(
        campaign_id="c1",
        channel=channel,
        specification=_specification(),
        guardrails=_guardrails(),
        plate_storage_key="org/campaign/plate.png",
        logo_storage_key="org/brand/logo.png",
        source_asset_id="asset-1",
        **overrides,
    )


class TestBuildingALayout:
    def test_it_uses_the_channel_dimensions(self) -> None:
        """One table decides what an Instagram story is — the layout engine and
        the prompt compiler must not disagree."""
        for channel in Channel:
            layout = _layout(channel)
            assert (layout.width, layout.height) == CHANNEL_DIMENSIONS[channel]

    def test_the_copy_comes_from_the_approved_specification(self) -> None:
        layout = _layout()
        headline = layout.by_role("headline")
        cta = layout.by_role("cta")
        assert headline is not None and cta is not None
        assert headline.content == "Built to outlast the building it clads"
        assert cta.content == "Request the specification pack"

    def test_the_logo_is_placed_only_when_the_brand_has_one(self) -> None:
        """No placeholder: a poster with an invented mark looks finished and
        cannot be used."""
        with_logo = _layout()
        assert any(e.type is ElementType.LOGO for e in with_logo.elements)

        without = build_layout(
            campaign_id="c1",
            channel=Channel.INSTAGRAM_POST,
            specification=_specification(),
            guardrails=_guardrails(),
            plate_storage_key="plate.png",
            logo_storage_key=None,
        )
        assert not any(e.type is ElementType.LOGO for e in without.elements)

    def test_the_scrim_uses_the_brands_darkest_colour(self) -> None:
        layout = _layout()
        assert layout.background_color == "#1F2933"

    def test_no_palette_falls_back_rather_than_inventing_one(self) -> None:
        layout = build_layout(
            campaign_id="c1",
            channel=Channel.INSTAGRAM_POST,
            specification=_specification(),
            guardrails=BrandGuardrails(),
            plate_storage_key="plate.png",
            logo_storage_key=None,
        )
        assert layout.background_color == "#111111"

    def test_it_carries_its_provenance(self) -> None:
        layout = _layout()
        assert layout.specification_version == 2
        assert layout.source_asset_id == "asset-1"
        assert layout.plate_storage_key == "org/campaign/plate.png"

    def test_every_channel_builds_a_valid_layout(self) -> None:
        """A default composition must be renderable without editing."""
        for channel in Channel:
            report = validate_layout(_layout(channel))
            assert report.verdict is LayoutVerdict.PASS, f"{channel.value}: {report.issues}"

    def test_a_banner_drops_the_subhead(self) -> None:
        """There is no room for a second line of readable type."""
        assert _layout(Channel.WEB_BANNER).by_role("subhead") is None
        assert _layout(Channel.INSTAGRAM_POST).by_role("subhead") is not None

    def test_the_legal_line_is_present_but_hidden_by_default(self) -> None:
        legal = _layout().by_role("legal")
        assert legal is not None
        assert legal.visible is False


class TestLayoutValidation:
    def test_a_good_layout_passes(self) -> None:
        assert validate_layout(_layout()).verdict is LayoutVerdict.PASS

    @pytest.mark.parametrize("channel", list(COMPOSABLE_CHANNELS), ids=lambda c: c.value)
    def test_the_default_layout_never_warns_about_itself(self, channel: Channel) -> None:
        """A default that flags its own scrim would train people to ignore the
        panel, which is worse than not warning at all.

        The safe area is a rule about *content*. The scrim band is meant to run
        edge to edge; the plate is meant to fill the frame.
        """
        report = validate_layout(_layout(channel))
        assert report.issues == [], f"{channel.value}: {[i.detail for i in report.issues]}"

    def test_a_full_bleed_scrim_is_not_flagged(self) -> None:
        layout = _layout()
        scrim = next(e for e in layout.elements if e.type is ElementType.SHAPE)
        left, top, right, bottom = _bounds(scrim.box)
        assert (left, right) == (0.0, 1.0), "the scrim is full-bleed by design"
        assert not any(issue.element_id == scrim.id for issue in validate_layout(layout).issues)

    def test_an_element_past_the_canvas_is_blocking(self) -> None:
        """`Box` refuses this at construction, so the only way to build one is
        to skip validation — which is exactly how a bad import or a future code
        path would. The report must still catch it."""
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None
        headline.__dict__["box"] = Box.model_construct(
            x=0.9, y=0.5, width=0.3, height=0.2, anchor=Anchor.TOP_LEFT
        )
        report = validate_layout(layout)
        assert report.verdict is LayoutVerdict.NEEDS_ADJUSTMENT
        assert any("past the canvas edge" in issue.detail for issue in report.blocking)

    def test_a_logo_outside_the_safe_area_is_blocking(self) -> None:
        """A clipped wordmark is an unusable deliverable, not a style choice."""
        layout = _layout()
        logo = next(e for e in layout.elements if e.type is ElementType.LOGO)
        logo.box = Box(x=0.0, y=0.0, width=0.2, height=0.08)
        report = validate_layout(layout)
        assert report.verdict is LayoutVerdict.NEEDS_ADJUSTMENT
        assert any("safe area" in issue.detail for issue in report.blocking)

    def test_the_cta_outside_the_safe_area_is_blocking(self) -> None:
        layout = _layout()
        cta = layout.by_role("cta")
        assert cta is not None
        cta.box = Box(x=0.01, y=0.97, width=0.5, height=0.02)
        assert validate_layout(layout).verdict is LayoutVerdict.NEEDS_ADJUSTMENT

    def test_a_non_critical_element_outside_the_safe_area_is_only_a_warning(self) -> None:
        layout = _layout()
        subhead = layout.by_role("subhead")
        assert subhead is not None
        subhead.box = Box(x=0.01, y=0.80, width=0.5, height=0.05)
        report = validate_layout(layout)
        assert report.verdict is LayoutVerdict.PASS
        assert any(issue.severity == "warning" for issue in report.issues)

    def test_text_larger_than_its_box_is_blocking(self) -> None:
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None and headline.text_style is not None
        headline.text_style.size = 0.5
        report = validate_layout(layout)
        assert report.verdict is LayoutVerdict.NEEDS_ADJUSTMENT
        assert any("larger than the space" in issue.detail for issue in report.blocking)

    def test_overlapping_text_is_blocking(self) -> None:
        layout = _layout()
        headline = layout.by_role("headline")
        cta = layout.by_role("cta")
        assert headline is not None and cta is not None
        cta.box = Box(x=headline.box.x, y=headline.box.y, width=0.5, height=0.15)
        report = validate_layout(layout)
        assert report.verdict is LayoutVerdict.NEEDS_ADJUSTMENT
        assert any("overlaps" in issue.detail for issue in report.blocking)

    def test_a_hidden_element_is_not_validated(self) -> None:
        """An invisible element cannot clip anything."""
        layout = _layout()
        subhead = layout.by_role("subhead")
        assert subhead is not None
        subhead.box = Box(x=0.0, y=0.0, width=0.3, height=0.02)
        subhead.visible = False
        assert validate_layout(layout).verdict is LayoutVerdict.PASS

    def test_every_issue_suggests_a_fix(self) -> None:
        layout = _layout()
        logo = next(e for e in layout.elements if e.type is ElementType.LOGO)
        logo.box = Box(x=0.0, y=0.0, width=0.2, height=0.08)
        for issue in validate_layout(layout).blocking:
            assert issue.suggested_fix

    def test_protected_roles_are_named(self) -> None:
        assert "cta" in PROTECTED_ROLES


class TestRendering:
    def _inputs(self) -> RenderInputs:
        return RenderInputs(plate=_plate(), logo=_logo())

    def test_it_produces_a_valid_png_at_the_channel_size(self) -> None:
        result = render(_layout(), self._inputs())
        assert result.mime_type == "image/png"
        assert (result.width, result.height) == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_POST]
        with Image.open(io.BytesIO(result.data)) as image:
            assert image.size == (result.width, result.height)

    def test_it_is_deterministic(self) -> None:
        """The guarantee everything else rests on."""
        layout, inputs = _layout(), self._inputs()
        first = render(layout, inputs)
        second = render(layout, inputs)
        assert first.data == second.data

    def test_the_same_layout_renders_the_same_on_a_fresh_object(self) -> None:
        inputs = self._inputs()
        first = render(_layout(), inputs)
        second = render(_layout(), inputs)
        assert first.data == second.data

    def test_it_stamps_the_renderer_version(self) -> None:
        assert render(_layout(), self._inputs()).renderer_version == RENDERER_VERSION

    def test_jpeg_export_works_and_reports_its_type(self) -> None:
        result = render(_layout(), self._inputs(), fmt="JPEG")
        assert result.mime_type == "image/jpeg"
        with Image.open(io.BytesIO(result.data)) as image:
            assert image.format == "JPEG"

    def test_every_channel_renders(self) -> None:
        inputs = self._inputs()
        for channel in Channel:
            result = render(_layout(channel), inputs)
            assert (result.width, result.height) == CHANNEL_DIMENSIONS[channel]

    def test_the_plate_actually_reaches_the_canvas(self) -> None:
        """A distinctive plate colour must be visible in the output — proof the
        composition is drawing the generated image, not a blank ground."""
        inputs = RenderInputs(plate=_plate(colour=(200, 30, 40)), logo=_logo())
        result = render(_layout(), inputs)
        with Image.open(io.BytesIO(result.data)) as image:
            # Sample well above the scrim band.
            pixel = image.convert("RGB").getpixel((image.width // 2, int(image.height * 0.15)))
        assert pixel[0] > 150 and pixel[1] < 90

    def test_the_approved_brand_colour_reaches_the_pixels_exactly(self) -> None:
        """Not "close to the brand colour" — the brand colour.

        The layout takes its ground from the brand's own palette, and the
        renderer must put that exact value on the canvas. An approximate brand
        colour is an off-brand asset.
        """
        layout = _layout()
        assert layout.background_color == "#1F2933", "the ground comes from the palette"

        # No plate, so the ground is the brand colour rather than an image.
        result = render(layout, RenderInputs(logo=_logo()))
        with Image.open(io.BytesIO(result.data)) as image:
            # Top-left, above the scrim and clear of every element.
            pixel = image.convert("RGB").getpixel((2, 2))
        assert pixel == (0x1F, 0x29, 0x33)

    def test_text_is_actually_drawn(self) -> None:
        """Rendering with and without the copy must differ."""
        layout = _layout()
        with_text = render(layout, self._inputs())

        stripped = _layout()
        for element in stripped.elements:
            if element.type is ElementType.TEXT:
                element.visible = False
        without_text = render(stripped, self._inputs())
        assert with_text.data != without_text.data

    def test_the_logo_is_drawn(self) -> None:
        layout = _layout()
        with_logo = render(layout, self._inputs())

        stripped = _layout()
        for element in stripped.elements:
            if element.type is ElementType.LOGO:
                element.visible = False
        assert with_logo.data != render(stripped, self._inputs()).data

    def test_a_missing_logo_is_an_error_not_a_placeholder(self) -> None:
        with pytest.raises(RenderError, match="no approved logo"):
            render(_layout(), RenderInputs(plate=_plate(), logo=None))

    def test_a_corrupt_plate_is_a_clear_error(self) -> None:
        with pytest.raises(RenderError, match="not a readable image"):
            render(_layout(), RenderInputs(plate=b"not an image", logo=_logo()))

    def test_rendering_without_a_plate_still_works(self) -> None:
        """Export must survive a failed generation — a flat brand ground is a
        usable fallback, a crash is not."""
        layout = _layout()
        layout.plate_storage_key = None
        result = render(layout, RenderInputs(plate=None, logo=_logo()))
        assert result.width > 0

    def test_an_invalid_layout_is_refused_before_any_pixels(self) -> None:
        layout = _layout()
        logo = next(e for e in layout.elements if e.type is ElementType.LOGO)
        logo.box = Box(x=0.0, y=0.0, width=0.2, height=0.08)
        with pytest.raises(RenderError, match="cannot be rendered"):
            render(layout, self._inputs())


class TestTextOverflow:
    def test_long_copy_is_wrapped_rather_than_clipped(self) -> None:
        """Copy too long for one line still renders — the renderer wraps it,
        and shrinks within its floor if the wrap needs more room."""
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None
        headline.content = "Engineered to outlast the building it clads, season after season"
        assert render(layout, RenderInputs(plate=_plate(), logo=_logo())).width > 0

    def test_copy_that_cannot_fit_is_refused_not_overflowed(self) -> None:
        """Pillow is never allowed to produce a poster with type off the edge."""
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None and headline.text_style is not None
        headline.content = "Engineering " * 200
        headline.text_style.max_lines = 2
        with pytest.raises(RenderError, match="does not fit"):
            render(layout, RenderInputs(plate=_plate(), logo=_logo()))

    def test_a_word_too_wide_for_its_box_is_refused_not_run_off_the_edge(self) -> None:
        """Vertical fit is not fit.

        An unbreakable word wraps to one line, so the line count and the block
        height are both fine — and the glyphs still run past the right edge and
        off the poster. The fit loop has to measure width too, or "text never
        silently overflows" is only true for copy that happens to contain
        spaces.
        """
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None
        headline.content = "Unbreakable" + "supercalifragilisticexpialidocious" * 2

        with pytest.raises(RenderError, match="does not fit"):
            render(layout, RenderInputs(plate=_plate(), logo=_logo()))

    def test_the_shrink_floor_is_published(self) -> None:
        """Below this, type is too small to read, and shrinking further would
        be a worse failure than refusing."""
        assert 0.0 < MIN_SCALE < 1.0

    def test_a_single_long_word_does_not_break_the_render(self) -> None:
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None
        headline.content = "Supercalifragilisticexpialidocious"
        assert render(layout, RenderInputs(plate=_plate(), logo=_logo())).width > 0

    def test_whitespace_only_text_is_skipped_rather_than_drawn(self) -> None:
        """The element model refuses empty content, so this can only arrive by
        skipping validation. The renderer must not then draw a blank line or
        crash measuring one."""
        layout = _layout()
        headline = layout.by_role("headline")
        assert headline is not None
        headline.__dict__["content"] = "   "
        assert render(layout, RenderInputs(plate=_plate(), logo=_logo())).width > 0


class TestChannelVariants:
    def test_a_variant_keeps_the_copy_and_changes_the_frame(self) -> None:
        """A variant is a re-layout, never a second design."""
        base = _layout(Channel.INSTAGRAM_POST)
        story = adapt_to_channel(base, Channel.INSTAGRAM_STORY)

        assert (story.width, story.height) == CHANNEL_DIMENSIONS[Channel.INSTAGRAM_STORY]
        assert story.by_role("headline") is not None
        base_headline = base.by_role("headline")
        story_headline = story.by_role("headline")
        assert base_headline is not None and story_headline is not None
        assert story_headline.content == base_headline.content
        assert story.by_role("cta") is not None
        assert story.by_role("cta").content == base.by_role("cta").content  # type: ignore[union-attr]

    def test_the_plate_is_not_regenerated(self) -> None:
        base = _layout()
        for channel in Channel:
            assert adapt_to_channel(base, channel).plate_storage_key == base.plate_storage_key

    def test_every_variant_is_valid(self) -> None:
        base = _layout(Channel.INSTAGRAM_POST)
        for channel in Channel:
            report = validate_layout(adapt_to_channel(base, channel))
            assert report.verdict is LayoutVerdict.PASS, f"{channel.value}: {report.issues}"

    def test_every_variant_renders(self) -> None:
        base = _layout(Channel.INSTAGRAM_POST)
        inputs = RenderInputs(plate=_plate(), logo=_logo())
        for channel in Channel:
            result = render(adapt_to_channel(base, channel), inputs)
            assert (result.width, result.height) == CHANNEL_DIMENSIONS[channel]

    def test_a_variant_uses_the_channels_own_safe_area(self) -> None:
        """A story's chrome eats the top and bottom; a square post's does not."""
        base = _layout(Channel.INSTAGRAM_POST)
        story = adapt_to_channel(base, Channel.INSTAGRAM_STORY)
        assert story.safe_area == SAFE_AREAS[Channel.INSTAGRAM_STORY]
        assert story.safe_area.bottom > base.safe_area.bottom

    def test_a_banner_variant_drops_the_subhead(self) -> None:
        base = _layout(Channel.INSTAGRAM_POST)
        assert base.by_role("subhead") is not None
        assert adapt_to_channel(base, Channel.WEB_BANNER).by_role("subhead") is None

    def test_a_variant_is_its_own_document(self) -> None:
        base = _layout()
        variant = adapt_to_channel(base, Channel.LINKEDIN, version=2)
        assert variant.id != base.id
        assert variant.version == 2
        # And the base is untouched.
        assert base.channel is Channel.INSTAGRAM_POST

    def test_adaptation_is_deterministic(self) -> None:
        base = _layout()
        first = adapt_to_channel(base, Channel.LINKEDIN)
        second = adapt_to_channel(base, Channel.LINKEDIN)
        assert first.model_dump(exclude={"id", "elements"}) == second.model_dump(
            exclude={"id", "elements"}
        )
        assert [e.box for e in first.elements] == [e.box for e in second.elements]

    def test_provenance_survives_adaptation(self) -> None:
        base = _layout()
        variant = adapt_to_channel(base, Channel.FACEBOOK)
        assert variant.specification_version == base.specification_version
        assert variant.source_asset_id == base.source_asset_id


class TestVersioning:
    def test_editing_a_copy_leaves_the_original_untouched(self) -> None:
        """v1 must keep rendering exactly what it always rendered."""
        v1 = _layout()
        snapshot = v1.model_dump(mode="json")

        v2 = LayoutSpec.model_validate(v1.model_dump(exclude={"id"}) | {"version": 2})
        headline = v2.by_role("headline")
        assert headline is not None
        headline.content = "A different headline"

        assert v1.model_dump(mode="json") == snapshot
        assert v1.by_role("headline").content != "A different headline"  # type: ignore[union-attr]

    def test_two_versions_render_differently(self) -> None:
        inputs = RenderInputs(plate=_plate(), logo=_logo())
        v1 = _layout()
        v2 = LayoutSpec.model_validate(v1.model_dump(exclude={"id"}) | {"version": 2})
        headline = v2.by_role("headline")
        assert headline is not None
        headline.content = "A different headline"
        assert render(v1, inputs).data != render(v2, inputs).data


class TestSafeAreasAreDefinedForEveryChannel:
    def test_no_channel_falls_through_to_a_guess(self) -> None:
        assert set(SAFE_AREAS) == set(Channel)

    def test_a_story_reserves_more_than_a_square_post(self) -> None:
        story = SAFE_AREAS[Channel.INSTAGRAM_STORY]
        post = SAFE_AREAS[Channel.INSTAGRAM_POST]
        assert story.top > post.top and story.bottom > post.bottom


class TestElementLevelGuards:
    def test_a_text_element_requires_content(self) -> None:
        with pytest.raises(ValueError):
            LayoutElement(type=ElementType.TEXT, box=Box(x=0, y=0, width=0.5, height=0.1))

    def test_a_logo_element_requires_a_storage_key(self) -> None:
        with pytest.raises(ValueError):
            LayoutElement(type=ElementType.LOGO, box=Box(x=0, y=0, width=0.2, height=0.1))

    def test_a_box_cannot_extend_past_the_canvas(self) -> None:
        with pytest.raises(ValueError, match="past the canvas"):
            Box(x=0.8, y=0.1, width=0.5, height=0.2)

    def test_a_safe_area_is_normalised(self) -> None:
        with pytest.raises(ValueError):
            SafeArea(top=1.4)

    def test_a_text_style_colour_must_be_hex(self) -> None:
        with pytest.raises(ValueError):
            TextStyle(color="cornflower")
