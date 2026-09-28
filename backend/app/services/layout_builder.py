"""Building a composition from approved data.

Turns an approved Creative Specification, an approved plate and the Brand Brain
into a `LayoutSpec` — deterministically, and using *only* values a human has
already signed off.

**Nothing here invents a brand element.** The headline and call to action come
from the approved Creative Specification; the logo from the brand's own asset
or not at all; the colours from the brand palette where one exists. A composer
that filled a gap with something plausible would produce a poster that looks
finished and is not usable.

**One layout per channel, derived from the same approved content.** The
geometry adapts to the frame — a story is tall and its chrome eats the top and
bottom, a banner is wide and has room for nothing but a line — while the words
and the logo stay identical. That is what makes a variant a *variant* rather
than a second design.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.common import CHANNEL_DIMENSIONS, Channel
from app.domain.creative import CreativeSpecification, copy_for
from app.domain.creative_context import BrandGuardrails
from app.domain.layout import (
    Box,
    ElementType,
    LayoutElement,
    LayoutSpec,
    SafeArea,
    TextStyle,
)

#: Channel chrome, as a fraction of the canvas. A story has a caption bar and a
#: profile row; a banner has almost no vertical room to give away. These are
#: the margins nothing important may enter, and they are per-channel because
#: one number would be wrong everywhere.
SAFE_AREAS: dict[Channel, SafeArea] = {
    Channel.INSTAGRAM_POST: SafeArea(top=0.06, right=0.06, bottom=0.06, left=0.06),
    # Slightly deeper at the bottom than the square: the feed's own caption and
    # action row sits immediately beneath a 4:5 frame, so the last band of the
    # canvas is the first thing a thumb covers.
    Channel.INSTAGRAM_PORTRAIT: SafeArea(top=0.06, right=0.06, bottom=0.08, left=0.06),
    Channel.INSTAGRAM_STORY: SafeArea(top=0.14, right=0.06, bottom=0.16, left=0.06),
    Channel.LINKEDIN: SafeArea(top=0.07, right=0.05, bottom=0.07, left=0.05),
    Channel.FACEBOOK: SafeArea(top=0.07, right=0.05, bottom=0.07, left=0.05),
    Channel.WEB_BANNER: SafeArea(top=0.08, right=0.04, bottom=0.08, left=0.04),
    Channel.PRINT_A3: SafeArea(top=0.08, right=0.08, bottom=0.08, left=0.08),
    Channel.PRINT_A4: SafeArea(top=0.08, right=0.08, bottom=0.08, left=0.08),
}

#: Type scale per channel, as a fraction of canvas height. A wide banner needs
#: proportionally larger type than a square post to stay readable at the size
#: it is actually seen.
_HEADLINE_SIZE: dict[Channel, float] = {
    Channel.INSTAGRAM_POST: 0.075,
    # A fraction of a taller canvas. 0.065 of 1350px lands near the square's
    # 0.075 of 1080px in absolute pixels, which is the size the two are
    # actually read at side by side in the same feed.
    Channel.INSTAGRAM_PORTRAIT: 0.065,
    Channel.INSTAGRAM_STORY: 0.055,
    Channel.LINKEDIN: 0.105,
    Channel.FACEBOOK: 0.105,
    Channel.WEB_BANNER: 0.105,
    Channel.PRINT_A3: 0.06,
    Channel.PRINT_A4: 0.06,
}

#: Type colour. Deliberately not taken from the brand palette: the copy sits on
#: a scrim over a photographic plate, and light-on-dark is the one setting that
#: stays legible whatever the plate turns out to be. A brand colour for type is
#: an editor decision, made against a render a human can see.
_INK = "#FFFFFF"
#: Used when the brand defines no palette. A neutral near-black is better than
#: an invented brand colour.
_FALLBACK_SCRIM = "#111111"


def build_layout(
    *,
    campaign_id: str,
    channel: Channel,
    specification: CreativeSpecification,
    guardrails: BrandGuardrails,
    plate_storage_key: str | None,
    logo_storage_key: str | None,
    source_asset_id: str | None = None,
    version: int = 1,
) -> LayoutSpec:
    """Compose the default layout for one channel.

    A starting point a human then edits, not a finished decision — but a
    starting point that is already valid, on-brand and built from approved
    copy, so the common case needs no editing at all.
    """
    width, height = CHANNEL_DIMENSIONS[channel]
    safe = SAFE_AREAS.get(channel, SafeArea())
    # One resolver, never a fallback expression here: this channel's words may
    # differ from the specification's defaults, and the guard that protects the
    # call to action has to be looking at the same answer.
    copy = copy_for(specification, channel)
    geometry = _geometry(channel, has_subhead=bool(copy.subhead))
    headline_size = _HEADLINE_SIZE.get(channel, 0.075)

    spec = LayoutSpec(
        campaign_id=campaign_id,
        channel=channel,
        version=version,
        width=width,
        height=height,
        source_asset_id=source_asset_id,
        specification_version=specification.version,
        plate_storage_key=plate_storage_key,
        background_color=_scrim_colour(guardrails),
        safe_area=safe,
        elements=[],
    )

    # A flat scrim band behind the copy. Flat rather than gradient because a
    # flat fill is exactly reproducible and a gradient is one more thing to get
    # subtly wrong between renders.
    spec.elements.append(
        LayoutElement(
            type=ElementType.SHAPE,
            box=Box(
                x=0.0,
                y=geometry.copy_top,
                width=1.0,
                height=1.0 - geometry.copy_top,
            ),
            fill=_scrim_colour(guardrails),
            opacity=0.55,
            z=10,
        )
    )

    spec.elements.append(_headline_element(copy.headline, geometry, safe, headline_size))
    if geometry.has_subhead and copy.subhead:
        spec.elements.append(_subhead_element(copy.subhead, geometry, safe, headline_size))
    spec.elements.append(_cta_element(copy.cta, geometry, safe, headline_size))

    # The logo only when the brand actually has one. No placeholder: a poster
    # with an invented mark looks finished and cannot be used.
    if logo_storage_key:
        spec.elements.append(_logo_element(logo_storage_key, channel, safe))

    if guardrails.legal_line:
        spec.elements.append(_legal_element(guardrails.legal_line, safe))

    return spec


def adapt_to_channel(
    source: LayoutSpec,
    channel: Channel,
    *,
    version: int = 1,
    specification: CreativeSpecification | None = None,
) -> LayoutSpec:
    """The same composition, re-laid for a different frame.

    A variant is a re-layout, never a regeneration: the plate and the logo are
    identical and only the geometry moves. That is why an Instagram post and a
    story are recognisably the same creative, and why a second aspect ratio
    costs nothing but a render.

    **The copy is the one thing that may differ.** Pass `specification` and the
    target channel's approved words are used; omit it and the source's words
    are carried across exactly as before. Optional rather than required so the
    function stays a pure re-layout for callers that have no specification to
    hand — and so a variant built before overrides existed still resolves
    identically.
    """
    width, height = CHANNEL_DIMENSIONS[channel]
    safe = SAFE_AREAS.get(channel, SafeArea())
    copy = copy_for(specification, channel) if specification is not None else None

    # A variant is its own document, so the id is dropped and a fresh one
    # minted. Everything else — the plate, the copy, the logo — is carried
    # across untouched; only geometry moves below.
    adapted = LayoutSpec.model_validate(
        source.model_dump(mode="json", exclude={"id"})
        | {
            "channel": channel.value,
            "version": version,
            "width": width,
            "height": height,
            "safe_area": safe.model_dump(mode="json"),
        }
    )

    # A re-layout moves what is there; it never adds an element. So a subhead
    # is possible only if the source carries one — reserving space for copy
    # with no element to fill it would leave a gap the renderer cannot see.
    carries_subhead = any(e.role == "subhead" for e in adapted.elements)
    has_subhead = carries_subhead and (bool(copy.subhead) if copy else True)
    geometry = _geometry(channel, has_subhead=has_subhead)
    headline_size = _HEADLINE_SIZE.get(channel, 0.075)
    kept: list[LayoutElement] = []

    for element in adapted.elements:
        # This channel's own words, where it has them. Done before the geometry
        # below, because a shorter headline is exactly why someone overrode it.
        if copy is not None and element.role in ("headline", "subhead", "cta"):
            replacement_text = getattr(copy, element.role)
            if replacement_text:
                element.content = replacement_text

        if element.role == "subhead" and not geometry.has_subhead:
            # Dropped rather than shrunk: a banner has no room for a second
            # line of readable type.
            continue

        if element.type is ElementType.SHAPE:
            element.box = Box(x=0.0, y=geometry.copy_top, width=1.0, height=1.0 - geometry.copy_top)
        elif element.role == "headline":
            replacement = _headline_element(element.content or "", geometry, safe, headline_size)
            element.box, element.text_style = replacement.box, replacement.text_style
        elif element.role == "subhead":
            replacement = _subhead_element(element.content or "", geometry, safe, headline_size)
            element.box, element.text_style = replacement.box, replacement.text_style
        elif element.role == "cta":
            replacement = _cta_element(element.content or "", geometry, safe, headline_size)
            element.box, element.text_style = replacement.box, replacement.text_style
        elif element.type is ElementType.LOGO:
            element.box = _logo_element(element.storage_key or "", channel, safe).box
        elif element.role == "legal":
            element.box = _legal_element(element.content or "", safe).box
        kept.append(element)

    adapted.elements = kept
    return adapted


@dataclass(frozen=True)
class _Geometry:
    """Where each block sits, for one channel.

    Computed by stacking **upward from the call to action**, which is pinned
    just inside the bottom safe area. Laying out downward from a guessed top
    is how the print channels ended up with the subhead on top of the CTA:
    with a fixed start and independent heights, some frame eventually collides.
    Stacking from a fixed bottom makes that impossible by construction.
    """

    copy_top: float
    headline_top: float
    headline_height: float
    subhead_top: float
    subhead_height: float
    cta_top: float
    cta_height: float
    has_subhead: bool


#: Breathing room between stacked blocks, as a fraction of canvas height.
_GAP = 0.02


def _geometry(channel: Channel, *, has_subhead: bool) -> _Geometry:
    width, height = CHANNEL_DIMENSIONS[channel]
    safe = SAFE_AREAS.get(channel, SafeArea())
    wide = width > height * 1.4

    # A banner has no room for a second line of readable type.
    subhead = has_subhead and not wide

    cta_height = 0.06 if not wide else 0.09
    cta_top = 1.0 - safe.bottom - cta_height - _GAP

    subhead_height = 0.09 if subhead else 0.0
    subhead_top = cta_top - _GAP - subhead_height if subhead else cta_top

    headline_height = 0.30 if wide else 0.22
    headline_top = subhead_top - _GAP - headline_height

    return _Geometry(
        copy_top=headline_top - 0.04,
        headline_top=headline_top,
        headline_height=headline_height,
        subhead_top=subhead_top,
        subhead_height=subhead_height,
        cta_top=cta_top,
        cta_height=cta_height,
        has_subhead=subhead,
    )


def _scrim_colour(guardrails: BrandGuardrails) -> str:
    """The brand's darkest approved colour, so the scrim is *their* black.

    Falls back to a near-black when the brand defines no palette: an invented
    brand colour is worse than a neutral one.
    """
    candidates = [colour for colour in guardrails.palette if _is_hex(colour)]
    if not candidates:
        return _FALLBACK_SCRIM
    return min(candidates, key=_luminance)


def _is_hex(value: str) -> bool:
    stripped = value.strip().lstrip("#")
    return len(stripped) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in stripped)


def _luminance(hex_colour: str) -> float:
    value = hex_colour.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# Element factories — one definition each, used by both build and adapt, so a
# variant is laid out by exactly the rules that laid out the original.
# ---------------------------------------------------------------------------
def _headline_element(
    content: str, geometry: _Geometry, safe: SafeArea, size: float
) -> LayoutElement:
    return LayoutElement(
        type=ElementType.TEXT,
        role="headline",
        content=content,
        box=Box(
            x=safe.left,
            y=geometry.headline_top,
            width=1.0 - safe.left - safe.right,
            height=geometry.headline_height,
        ),
        text_style=TextStyle(
            size=size,
            color=_INK,
            align="left",
            font_weight="bold",
            max_lines=2 if geometry.headline_height > 0.25 else 3,
            line_height=1.12,
        ),
        z=20,
    )


def _subhead_element(
    content: str, geometry: _Geometry, safe: SafeArea, size: float
) -> LayoutElement:
    return LayoutElement(
        type=ElementType.TEXT,
        role="subhead",
        content=content,
        box=Box(
            x=safe.left,
            y=geometry.subhead_top,
            width=1.0 - safe.left - safe.right,
            height=geometry.subhead_height,
        ),
        text_style=TextStyle(
            size=size * 0.45, color=_INK, align="left", font_weight="regular", max_lines=2
        ),
        z=20,
    )


def _cta_element(content: str, geometry: _Geometry, safe: SafeArea, size: float) -> LayoutElement:
    return LayoutElement(
        type=ElementType.TEXT,
        role="cta",
        content=content,
        box=Box(
            x=safe.left,
            y=geometry.cta_top,
            width=min(0.6, 1.0 - safe.left - safe.right),
            height=geometry.cta_height,
        ),
        text_style=TextStyle(
            size=size * 0.4,
            color=_INK,
            align="left",
            font_weight="bold",
            max_lines=1,
            uppercase=True,
            letter_spacing=0.02,
        ),
        z=20,
    )


def _logo_element(storage_key: str, channel: Channel, safe: SafeArea) -> LayoutElement:
    width, height = CHANNEL_DIMENSIONS[channel]
    wide = width > height * 1.4
    logo_width = 0.14 if wide else 0.22
    return LayoutElement(
        type=ElementType.LOGO,
        role="logo",
        storage_key=storage_key,
        box=Box(
            x=1.0 - safe.right - logo_width,
            y=safe.top,
            width=logo_width,
            height=0.09,
        ),
        fit="contain",
        z=30,
    )


def _legal_element(content: str, safe: SafeArea) -> LayoutElement:
    """Present but hidden by default: a legal line is a deliberate choice, and
    a poster that grew one without being asked is a surprise."""
    return LayoutElement(
        type=ElementType.TEXT,
        role="legal",
        content=content,
        box=Box(
            x=safe.left,
            y=1.0 - safe.bottom + 0.005,
            width=1.0 - safe.left - safe.right,
            height=0.02,
        ),
        text_style=TextStyle(size=0.014, color=_INK, align="left", max_lines=1),
        z=20,
        visible=False,
    )
