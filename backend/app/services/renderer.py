"""The deterministic composition renderer (ADR-006).

The image model produced a *plate*. This draws the brand on top of it: the
logo, the headline, the call to action, the exact colours, inside the safe
areas. Generative models are unreliable at every one of those, and reliably
good at none of them — so none of them are asked of a model here.

`render` is a **pure function**: `(LayoutSpec, plate bytes, logo bytes, font
bytes) -> PNG bytes`. Same inputs, same pixels, on any machine. That is what
makes a brand deliverable trustworthy, makes eight channel variants a loop
rather than eight generations, and makes the editor a *data* editor.

**Text never silently overflows.** A line that does not fit is wrapped; a block
that still does not fit is scaled down within a published floor; a block that
cannot fit even then is a blocking layout error reported before rendering
starts. Pillow is never allowed to produce a poster with type running off the
edge.

**The typeface is the brand's own where one exists.** A brand may upload a font
asset, and the renderer uses it. Where none exists it falls back to the font
Pillow bundles — deterministic, shipped with the dependency, and not a guess at
someone else's typeface (ADR-011).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.domain.layout import (
    RENDERER_VERSION,
    Box,
    ElementType,
    LayoutElement,
    LayoutSpec,
    TextStyle,
    validate_layout,
)
from app.logging import get_logger

log = get_logger(__name__)

#: How far the renderer may shrink text to make it fit before giving up and
#: reporting the layout as impossible. Below this, type is too small to read
#: and silently shrinking it would be a worse failure than refusing.
MIN_SCALE = 0.6


class RenderError(ValueError):
    """The composition could not be rendered. Never a partial image."""


@dataclass(frozen=True)
class RenderInputs:
    """Everything the renderer draws from. Bytes, not keys: fetching is the
    caller's job, which keeps this function pure and trivially testable."""

    plate: bytes | None = None
    logo: bytes | None = None
    #: A brand-uploaded TTF/OTF. `None` falls back to Pillow's bundled face.
    font: bytes | None = None


@dataclass(frozen=True)
class RenderedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    renderer_version: str = RENDERER_VERSION


def render(spec: LayoutSpec, inputs: RenderInputs, *, fmt: str = "PNG") -> RenderedImage:
    """Compose one final branded asset.

    Raises `RenderError` when the layout cannot produce a valid poster — a
    clipped logo, type that will not fit, a plate that is not an image. A
    broken deliverable is worse than an error.
    """
    report = validate_layout(spec)
    if not report.can_render():
        detail = "; ".join(issue.detail for issue in report.blocking)
        raise RenderError(f"This layout cannot be rendered: {detail}")

    canvas = Image.new("RGB", (spec.width, spec.height), _rgb(spec.background_color))
    if inputs.plate:
        canvas.paste(_fit(_open(inputs.plate, "plate"), spec.width, spec.height), (0, 0))

    draw = ImageDraw.Draw(canvas, "RGBA")
    for element in spec.ordered():
        if element.type is ElementType.SHAPE:
            _draw_shape(draw, element, spec)
        elif element.type is ElementType.TEXT:
            _draw_text(canvas, draw, element, spec, inputs.font)
        elif element.type is ElementType.LOGO:
            _draw_logo(canvas, element, spec, inputs.logo)
        elif element.type is ElementType.IMAGE:
            _draw_image(canvas, element, spec, inputs.plate)

    buffer = io.BytesIO()
    if fmt.upper() in ("JPEG", "JPG"):
        canvas.save(buffer, format="JPEG", quality=92, optimize=True)
        mime = "image/jpeg"
    else:
        canvas.save(buffer, format="PNG", optimize=True)
        mime = "image/png"

    data = buffer.getvalue()
    _assert_readable(data)
    log.info(
        "asset_rendered",
        channel=spec.channel.value,
        layout_version=spec.version,
        size=f"{spec.width}x{spec.height}",
        renderer_version=RENDERER_VERSION,
    )
    return RenderedImage(data=data, mime_type=mime, width=spec.width, height=spec.height)


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------
def _draw_shape(draw: ImageDraw.ImageDraw, element: LayoutElement, spec: LayoutSpec) -> None:
    box = _pixels(element.box, spec)
    fill = (*_rgb(element.fill or "#000000"), int(255 * element.opacity))
    radius = int(min(box[2] - box[0], box[3] - box[1]) * element.radius)
    if radius:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    else:
        draw.rectangle(box, fill=fill)


def _draw_logo(
    canvas: Image.Image, element: LayoutElement, spec: LayoutSpec, logo: bytes | None
) -> None:
    """The approved logo, never an invented one.

    A layout that asks for a logo the brand has not provided is a hard error:
    drawing a placeholder would produce something that looks finished and is
    not usable.
    """
    if not logo:
        raise RenderError("This layout places a logo, but the brand has no approved logo asset.")
    left, top, right, bottom = _pixels(element.box, spec)
    image = _open(logo, "logo").convert("RGBA")
    # Always `contain` for a logo: a cropped wordmark is a brand violation, so
    # the element's `fit` is deliberately not honoured here.
    image.thumbnail((max(right - left, 1), max(bottom - top, 1)), Image.Resampling.LANCZOS)
    x = left + (right - left - image.width) // 2
    y = top + (bottom - top - image.height) // 2
    canvas.paste(image, (x, y), image)


def _draw_image(
    canvas: Image.Image, element: LayoutElement, spec: LayoutSpec, plate: bytes | None
) -> None:
    if not plate:
        return
    left, top, right, bottom = _pixels(element.box, spec)
    width, height = max(right - left, 1), max(bottom - top, 1)
    image = _open(plate, "image")
    canvas.paste(
        _fit(image, width, height) if element.fit == "cover" else _contain(image, width, height),
        (left, top),
    )


def _draw_text(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    element: LayoutElement,
    spec: LayoutSpec,
    font_bytes: bytes | None,
) -> None:
    style = element.text_style or TextStyle()
    content = (element.content or "").strip()
    if not content:
        return
    if style.uppercase:
        content = content.upper()

    left, top, right, bottom = _pixels(element.box, spec)
    width, height = right - left, bottom - top

    lines, font, line_height = _fit_text(content, style, spec, width, height, font_bytes)
    if lines is None:
        raise RenderError(
            f"{element.role or 'Text'} does not fit its box even at the smallest "
            "readable size. Give it more room or shorten the copy."
        )

    block = line_height * len(lines)
    if style.scrim:
        # Drawn behind the type so it stays legible over any plate — the
        # readability guarantee a generated image cannot make.
        pad = int(line_height * 0.35)
        draw.rectangle(
            (left - pad, top - pad, right + pad, top + block + pad),
            fill=(0, 0, 0, int(255 * style.scrim_opacity)),
        )

    colour = _rgb(style.color)
    y = top
    for line in lines:
        span = draw.textlength(line, font=font)
        if style.align == "center":
            x = left + (width - span) / 2
        elif style.align == "right":
            x = right - span
        else:
            x = left
        draw.text((x, y), line, font=font, fill=colour)
        y += line_height


def _fit_text(
    content: str,
    style: TextStyle,
    spec: LayoutSpec,
    width: int,
    height: int,
    font_bytes: bytes | None,
) -> tuple[list[str] | None, ImageFont.FreeTypeFont, int]:
    """Wrap, then shrink, then refuse.

    Returns the laid-out lines, the font that fits them, and the line height.
    `None` for the lines means no readable size works — the caller raises,
    because type running off a poster is not an acceptable outcome.
    """
    base = max(int(style.size * spec.height), 8)
    scale = 1.0
    font = _font(font_bytes, base)
    lines: list[str] = []

    while scale >= MIN_SCALE:
        size = max(int(base * scale), 8)
        font = _font(font_bytes, size)
        line_height = max(int(size * style.line_height), size)
        lines = _wrap(content, font, width)
        # Width as well as height. `_wrap` leaves an unbreakable word whole
        # rather than hyphenating it, so a single long word wraps to one line
        # that passes every vertical check and still runs off the poster.
        # Measuring the widest line is what makes "text never silently
        # overflows" true for copy that has no spaces to break at.
        widest = max((font.getlength(line) for line in lines), default=0.0)
        fits = (
            len(lines) <= style.max_lines and line_height * len(lines) <= height and widest <= width
        )
        if fits:
            return lines, font, line_height
        scale -= 0.05

    return None, font, max(int(base * MIN_SCALE * style.line_height), 8)


def _wrap(content: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Greedy word wrap at the measured width.

    A single word longer than the line is left whole rather than hyphenated:
    breaking a product name mid-word is worse than one line running wide, and
    the caller's shrink loop will resolve it or refuse.
    """
    lines: list[str] = []
    for paragraph in content.splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and font.getlength(candidate) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return [line for line in lines if line] or [""]


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------
@lru_cache(maxsize=64)
def _cached_default_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Cached because a poster re-measures the same size many times while the
    shrink loop searches for a fit."""
    return ImageFont.load_default(size=size)


def _font(font_bytes: bytes | None, size: int) -> ImageFont.FreeTypeFont:
    """The brand's typeface where it has one, Pillow's bundled face otherwise.

    Never a font found on the host machine: the same layout has to render
    identically on a laptop and a server, and "whatever Helvetica this box
    has" is not a guarantee.
    """
    if font_bytes:
        try:
            return ImageFont.truetype(io.BytesIO(font_bytes), size=size)
        except OSError:
            log.warning("brand_font_unreadable", falling_back=True)
    font = _cached_default_font(size)
    if not isinstance(font, ImageFont.FreeTypeFont):  # pragma: no cover - no FreeType build
        raise RenderError("This build of Pillow cannot render scalable text.")
    return font


def _open(data: bytes, what: str) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise RenderError(f"The {what} is not a readable image.") from exc
    return image.convert("RGB") if image.mode not in ("RGB", "RGBA") else image


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Cover: fill the frame, centre-cropping the overflow.

    Centre rather than top-left because a plate's subject is composed around
    the middle, and cropping from a corner is how a facade becomes a wall.
    """
    if image.width == 0 or image.height == 0:
        raise RenderError("The plate has no dimensions.")
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(int(image.width * scale), 1), max(int(image.height * scale), 1)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height)).convert("RGB")


def _contain(image: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    scaled = image.copy()
    scaled.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    return canvas


def _pixels(box: Box, spec: LayoutSpec) -> tuple[int, int, int, int]:
    """Normalised geometry to pixels, with the anchor resolved."""
    from app.domain.layout import _bounds

    left, top, right, bottom = _bounds(box)
    return (
        int(left * spec.width),
        int(top * spec.height),
        int(right * spec.width),
        int(bottom * spec.height),
    )


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _assert_readable(data: bytes) -> None:
    """The last guard: whatever we are about to store opens as an image."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001
        raise RenderError("The renderer produced an unreadable image.") from exc
