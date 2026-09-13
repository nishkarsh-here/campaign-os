"""Deterministic composition (ADR-006).

The image model produces a *plate*. This module describes everything drawn on
top of it — headline, subhead, CTA, logo, colour blocks, legal line — as data.

Rendering is a pure function:  (LayoutSpec, plate, brand assets) -> PNG.
Same inputs, same pixels. That is what makes brand output trustworthy, makes
eight channel variants a loop instead of eight generations, and makes the editor
a data editor rather than an image editor.

Geometry is normalised (0.0-1.0 of canvas width/height) so one spec re-lays out
across every aspect ratio without recomputing pixels.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from app.domain.common import (
    CHANNEL_DIMENSIONS,
    Channel,
    DomainModel,
    Id,
    new_id,
    utc_now,
)

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
HEX = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"

#: Bumped whenever the renderer's output could change for identical input.
#: Stamped on every final asset, so "why does this look different from last
#: month's?" has an answer that does not require diffing pixels.
RENDERER_VERSION = "r1"


class FinalAssetKind(StrEnum):
    """What a stored image actually is.

    `VISUAL_PLATE` is what an image model returned (Milestone 6). Only the
    deterministic composition pipeline produces `FINAL_BRANDED_ASSET`, and the
    distinction is enforced rather than described — a generated image never
    becomes brand-ready by being looked at.
    """

    FINAL_BRANDED_ASSET = "FINAL_BRANDED_ASSET"


class LayoutVerdict(StrEnum):
    PASS = "PASS"
    NEEDS_ADJUSTMENT = "NEEDS_ADJUSTMENT"


class ElementType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    LOGO = "logo"
    SHAPE = "shape"


class Anchor(StrEnum):
    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


class Box(DomainModel):
    """Normalised rectangle."""

    x: Unit
    y: Unit
    width: Unit
    height: Unit
    anchor: Anchor = Anchor.TOP_LEFT

    @model_validator(mode="after")
    def _within_canvas(self) -> Box:
        if self.x + self.width > 1.0001 or self.y + self.height > 1.0001:
            raise ValueError("Box extends past the canvas")
        return self


class TextStyle(DomainModel):
    font_family: str | None = Field(default=None, description="None = brand default.")
    font_weight: str = "bold"
    #: Normalised to canvas height, so text scales with the artboard.
    size: Unit = 0.06
    color: str = Field(default="#FFFFFF", pattern=HEX)
    align: str = Field(default="left", description="left | center | right")
    line_height: float = Field(default=1.15, ge=0.8, le=2.5)
    letter_spacing: float = 0.0
    max_lines: int = Field(default=3, ge=1, le=10)
    uppercase: bool = False
    #: Drawn behind the text so it stays legible over any plate. This is why the
    #: renderer can guarantee readability that a generated image cannot.
    scrim: bool = False
    scrim_opacity: float = Field(default=0.45, ge=0.0, le=1.0)


class LayoutElement(DomainModel):
    id: Id = Field(default_factory=new_id)
    type: ElementType
    box: Box
    z: int = 0
    visible: bool = True

    # TEXT
    content: str | None = None
    text_style: TextStyle | None = None
    #: What this text *is*, so a channel variant knows what it may drop.
    role: str | None = Field(default=None, description="headline | subhead | cta | legal | eyebrow")

    # IMAGE / LOGO
    storage_key: str | None = None
    fit: str = Field(default="cover", description="cover | contain")

    # SHAPE
    fill: str | None = Field(default=None, pattern=HEX)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    radius: float = Field(default=0.0, ge=0.0, le=0.5)

    @model_validator(mode="after")
    def _payload_matches_type(self) -> LayoutElement:
        if self.type is ElementType.TEXT and not self.content:
            raise ValueError("text element requires content")
        if self.type in (ElementType.IMAGE, ElementType.LOGO) and not self.storage_key:
            raise ValueError(f"{self.type} element requires storage_key")
        if self.type is ElementType.SHAPE and not self.fill:
            raise ValueError("shape element requires fill")
        return self


#: Text roles the layout draws, in the order a reader meets them.
TEXT_ROLES: tuple[str, ...] = ("eyebrow", "headline", "subhead", "cta", "legal")

#: Roles whose *content* is an approved campaign fact. The editor may move,
#: resize, restyle or hide them; it may not put different words in them without
#: the change being checked against the approved plan.
PROTECTED_ROLES: tuple[str, ...] = ("cta", "legal")


class SafeArea(DomainModel):
    """Margins nothing important may enter. Enforced by the renderer, not by
    hoping the model left room — and channel-specific, because a story has UI
    chrome top and bottom."""

    top: Unit = 0.06
    right: Unit = 0.06
    bottom: Unit = 0.06
    left: Unit = 0.06


class LayoutSpec(DomainModel):
    """The complete recipe for one rendered creative.

    The source of truth for final composition. The rendered PNG is an *output*
    of this, never the thing that is edited — which is what makes an edit a
    data change, a re-render reproducible, and eight channel variants a loop.
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    channel: Channel
    #: Bumped on every accepted edit. A new version is a new row; the old one
    #: keeps rendering exactly what it always rendered.
    version: int = Field(default=1, ge=1)
    width: int = Field(ge=64, le=8000)
    height: int = Field(ge=64, le=8000)

    # --- provenance: what this composition was built from -----------------
    #: The generated plate this composes. History, and the reason a final
    #: asset can be traced to the image it was made from.
    source_asset_id: Id | None = None
    #: The approved Creative Specification version whose headline, CTA and
    #: colours this layout carries.
    specification_version: int = Field(default=1, ge=1)

    #: The generated plate. None renders on a flat background colour — which is
    #: what keeps export working when generation failed.
    plate_storage_key: str | None = None
    background_color: str = Field(default="#111111", pattern=HEX)

    safe_area: SafeArea = Field(default_factory=SafeArea)
    elements: list[LayoutElement] = Field(default_factory=list)

    @classmethod
    def for_channel(cls, campaign_id: str, channel: Channel, **fields: object) -> LayoutSpec:
        """A blank artboard at the channel's canonical size.

        Dimensions come from `CHANNEL_DIMENSIONS` rather than being restated
        here: the layout engine and the prompt compiler must agree about what
        an Instagram story is, and one table is how that stays true.
        """
        w, h = CHANNEL_DIMENSIONS[channel]
        return cls(campaign_id=campaign_id, channel=channel, width=w, height=h, **fields)

    def by_role(self, role: str) -> LayoutElement | None:
        return next((e for e in self.elements if e.role == role), None)

    def ordered(self) -> list[LayoutElement]:
        return sorted((e for e in self.elements if e.visible), key=lambda e: e.z)


class FinalAsset(DomainModel):
    """A rendered, brand-composed, channel-sized deliverable.

    The `LayoutSpec` is carried **inline** as well as by id: it is the exact
    recipe that produced this file, and a later edit to the layout must not
    silently change what an already-exported asset claims to be. The id says
    which working document it came from; the snapshot says what it actually
    rendered.
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    #: A plate is what an image model returned. Only the deterministic
    #: composition pipeline produces `FINAL_BRANDED_ASSET`, and nothing
    #: upstream may claim the label.
    kind: FinalAssetKind = FinalAssetKind.FINAL_BRANDED_ASSET
    version: int = Field(default=1, ge=1)
    channel: Channel
    width: int
    height: int
    storage_key: str
    mime_type: str = "image/png"
    size_bytes: int | None = None

    # --- provenance -------------------------------------------------------
    source_asset_id: Id | None = None
    specification_version: int = Field(default=1, ge=1)
    layout_id: Id | None = None
    layout_version: int = Field(default=1, ge=1)
    #: Bumped whenever the renderer's output could change for identical input.
    renderer_version: str = RENDERER_VERSION
    created_at: datetime = Field(default_factory=utc_now)
    #: The exact recipe, frozen.
    layout_spec: LayoutSpec

    def trace(self) -> str:
        """One line naming everything this asset descends from."""
        return (
            f"campaign {self.campaign_id} · specification v{self.specification_version}"
            f" · layout v{self.layout_version} · {self.channel.value}"
            f" · renderer {self.renderer_version}"
        )


class ExportManifest(DomainModel):
    """What export produced, including what it could not. Partial success is a
    normal outcome and must be reported as such, never as failure."""

    campaign_id: Id
    requested: list[Channel]
    produced: list[FinalAsset] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict, description="channel -> reason")


# ---------------------------------------------------------------------------
# Deterministic layout validation
# ---------------------------------------------------------------------------
class LayoutIssue(DomainModel):
    """One thing wrong with a composition, in words a user can act on."""

    element_id: Id | None = None
    role: str | None = None
    #: `blocking` stops a render; `warning` is worth saying and does not.
    severity: str = Field(default="blocking", description="blocking | warning")
    detail: str = Field(max_length=300)
    suggested_fix: str | None = Field(default=None, max_length=200)


class LayoutReport(DomainModel):
    """Whether this composition can be rendered, and what is wrong if not.

    Computed, never asked of a model: every one of these is a geometric fact
    about numbers the layout already carries.
    """

    verdict: LayoutVerdict
    issues: list[LayoutIssue] = Field(default_factory=list)

    @property
    def blocking(self) -> list[LayoutIssue]:
        return [issue for issue in self.issues if issue.severity == "blocking"]

    def can_render(self) -> bool:
        return not self.blocking


#: Element types the safe area governs. Shapes and images are backdrop —
#: full-bleed by design — and the margins are a rule about content.
_CONTENT_TYPES: frozenset[ElementType] = frozenset({ElementType.TEXT, ElementType.LOGO})


def validate_layout(spec: LayoutSpec) -> LayoutReport:
    """Check a composition before a single pixel is drawn.

    Catches the failures that make a poster unusable — a clipped logo, a CTA
    outside the safe area, a headline with nowhere to go, two required elements
    on top of each other — while they are still numbers, which is far cheaper
    and far clearer than discovering them in a rendered image.
    """
    issues: list[LayoutIssue] = []
    safe = spec.safe_area
    visible = [element for element in spec.elements if element.visible]

    if spec.width < 64 or spec.height < 64:
        issues.append(
            LayoutIssue(detail="The canvas is too small to compose.", severity="blocking")
        )

    for element in visible:
        box = element.box
        left, top, right, bottom = _bounds(box)

        if right > 1.0001 or bottom > 1.0001 or left < -0.0001 or top < -0.0001:
            issues.append(
                LayoutIssue(
                    element_id=element.id,
                    role=element.role,
                    severity="blocking",
                    detail=f"{_name(element)} extends past the canvas edge.",
                    suggested_fix="Move it inward or make it smaller.",
                )
            )
            continue

        # The safe area is where channel chrome lives. A logo or CTA under it
        # is not a style choice, it is an unusable deliverable.
        #
        # Content only, for the same reason the overlap check looks only at
        # content: a scrim band is *meant* to run edge to edge, and the plate
        # is *meant* to fill the frame. Flagging backdrop here would put a
        # warning on every correct layout the builder produces, which teaches
        # people to ignore the panel — worse than not warning at all.
        outside = element.type in _CONTENT_TYPES and (
            left < safe.left - 0.0001
            or top < safe.top - 0.0001
            or right > 1 - safe.right + 0.0001
            or bottom > 1 - safe.bottom + 0.0001
        )
        if outside:
            critical = element.type is ElementType.LOGO or element.role in PROTECTED_ROLES
            issues.append(
                LayoutIssue(
                    element_id=element.id,
                    role=element.role,
                    severity="blocking" if critical else "warning",
                    detail=f"{_name(element)} sits outside the safe area.",
                    suggested_fix="Move it inside the margins for this channel.",
                )
            )

        if element.type is ElementType.TEXT and element.text_style is not None:
            # A line taller than its own box can never fit, whatever the
            # renderer does about wrapping.
            line = element.text_style.size * element.text_style.line_height
            if line > box.height + 0.0001:
                issues.append(
                    LayoutIssue(
                        element_id=element.id,
                        role=element.role,
                        severity="blocking",
                        detail=f"{_name(element)} is set larger than the space it has.",
                        suggested_fix="Reduce the text size or give the element more height.",
                    )
                )

    for first, second in _overlapping_pairs(visible):
        issues.append(
            LayoutIssue(
                element_id=first.id,
                role=first.role,
                severity="blocking",
                detail=f"{_name(first)} overlaps {_name(second)}.",
                suggested_fix="Move one of them; both must stay readable.",
            )
        )

    verdict = (
        LayoutVerdict.PASS
        if not any(issue.severity == "blocking" for issue in issues)
        else LayoutVerdict.NEEDS_ADJUSTMENT
    )
    return LayoutReport(verdict=verdict, issues=issues)


def _bounds(box: Box) -> tuple[float, float, float, float]:
    """Normalised left, top, right, bottom, with the anchor resolved.

    `x`/`y` mean different things depending on the anchor, and every geometric
    check below needs the same answer — so the resolution happens once, here.
    """
    x, y, w, h = box.x, box.y, box.width, box.height
    anchor = box.anchor.value
    if anchor.endswith("center") and anchor != "center":
        x = x - w / 2 if "top" in anchor or "bottom" in anchor else x
    if anchor == "center":
        x, y = x - w / 2, y - h / 2
    if anchor.endswith("right"):
        x = x - w
    if anchor.startswith("bottom"):
        y = y - h
    if anchor.startswith("center_"):
        y = y - h / 2
    return x, y, x + w, y + h


def _overlapping_pairs(elements: list[LayoutElement]) -> list[tuple[LayoutElement, LayoutElement]]:
    """Required elements that collide.

    Only text and logos are checked against each other: a shape *behind* text
    is a scrim doing its job, and an image is the plate. Two pieces of type on
    top of each other is always a mistake.
    """
    solid = [
        element for element in elements if element.type in (ElementType.TEXT, ElementType.LOGO)
    ]
    clashes: list[tuple[LayoutElement, LayoutElement]] = []
    for index, first in enumerate(solid):
        for second in solid[index + 1 :]:
            if _overlap_area(first.box, second.box) > 0.02:
                clashes.append((first, second))
    return clashes


def _overlap_area(first: Box, second: Box) -> float:
    """Shared area as a fraction of the canvas. A hairline touch is not a clash."""
    a_left, a_top, a_right, a_bottom = _bounds(first)
    b_left, b_top, b_right, b_bottom = _bounds(second)
    width = min(a_right, b_right) - max(a_left, b_left)
    height = min(a_bottom, b_bottom) - max(a_top, b_top)
    return width * height if width > 0 and height > 0 else 0.0


def _name(element: LayoutElement) -> str:
    if element.role:
        return element.role.capitalize()
    return element.type.value.capitalize()
