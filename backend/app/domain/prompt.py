"""Prompt compilation.

A prompt is a **build artefact** of an approved `CreativeSpecification`, never
the source of truth. Two models express that:

`CanonicalPrompt` is the provider-neutral, *structured* form — the specification
rearranged into the controls an image model actually responds to (subject,
environment, framing, light, colour, mood, constraints). It is structured rather
than a string on purpose: a string cannot be diffed, cannot be reformatted per
provider without re-parsing, and cannot be checked for a missing control.

`ModelPrompt` is one provider's rendering of that canonical form. Adapters
differ in *formatting*, never in meaning (ADR-005) — which is what lets two
providers produce the same creative idea.

Both carry the specification version they were compiled from, so any prompt can
be traced back to — and recompiled from — the approved plan that produced it.

**The image model does not render brand text** (ADR-006). The canonical prompt
therefore asks for a *visual plate* with a quiet area reserved for type, and
carries `no_text_in_image` into every provider's negative constraints. A prompt
that asked a model to set the headline would be asking the wrong renderer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import Field

from app.domain.common import DomainModel, Id, StyleFamily, new_id
from app.domain.creative import NegativeConstraints, TypographyGuidance

#: Every image the plate pipeline produces is a plate, not a finished creative.
#: Recorded explicitly so nothing downstream can mistake one for the other.
VISUAL_PLATE = "VISUAL_PLATE"


class CanonicalPrompt(DomainModel):
    """The approved Creative Specification, compiled into image controls.

    Fields mirror controls image models genuinely act on. Nothing is added
    merely to make the prompt longer: an unused control is noise that competes
    with the ones that matter.
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    specification_id: Id
    #: The Creative Specification version this was compiled from. A prompt
    #: whose specification has moved on is stale, and visibly so.
    specification_version: int = Field(default=1, ge=1)
    version: int = Field(default=1, ge=1)

    # --- what is in the frame -------------------------------------------
    subject: str
    environment: str
    visual_story: str = ""
    composition: str
    focal_point: str = ""
    camera: str | None = None
    lighting: str
    color_direction: str = ""
    palette: list[str] = Field(default_factory=list, max_length=8)
    mood: list[str] = Field(default_factory=list, max_length=8)
    style_families: list[StyleFamily] = Field(default_factory=list, max_length=4)

    # --- what the campaign requires of it -------------------------------
    product_integration: str = ""
    people_guidance: str = ""
    brand_integration: str = ""
    #: Region only where the Campaign Specification already established it.
    #: The compiler never invents a regional cue (PRODUCT_SPEC §8).
    regional_cues: list[str] = Field(default_factory=list, max_length=6)

    # --- what must be left to the deterministic renderer ------------------
    typography_guidance: TypographyGuidance = Field(default_factory=TypographyGuidance)
    #: Where the composition must stay quiet so type can be laid over it.
    #: This is the *only* way typography reaches an image model (ADR-006).
    text_safe_area: str = ""

    # --- what must not appear --------------------------------------------
    negative_constraints: NegativeConstraints = Field(default_factory=NegativeConstraints)
    #: Abstract qualities carried from references — never their content
    #: (ADR-011). `ReferenceAnalysis.forbids_reproduction()` decides what is
    #: eligible; this list only ever holds what survived that check.
    reference_characteristics: list[str] = Field(default_factory=list, max_length=8)

    aspect_ratio: str = "1:1"

    #: Digest of the specification fields this was compiled from. Two compiles
    #: of the same specification produce the same fingerprint, which is how
    #: "is this prompt still reproducible from its source?" is answered
    #: without storing the specification twice.
    source_fingerprint: str = ""

    def render(self) -> str:
        """The neutral rendering. Adapters may reformat it; they must not add
        meaning that is not already in these fields."""
        parts: list[str] = [
            f"Subject: {self.subject}",
            f"Setting: {self.environment}",
        ]
        if self.visual_story:
            parts.append(f"Scene: {self.visual_story}")
        parts.append(f"Composition: {self.composition}")
        if self.focal_point:
            parts.append(f"Focal point: {self.focal_point}")
        if self.camera:
            parts.append(f"Camera: {self.camera}")
        parts.append(f"Lighting: {self.lighting}")
        if self.color_direction:
            parts.append(f"Colour: {self.color_direction}")
        if self.palette:
            parts.append(f"Palette: {', '.join(self.palette)}")
        if self.mood:
            parts.append(f"Mood: {', '.join(self.mood)}")
        if self.style_families:
            parts.append(f"Style: {', '.join(s.value for s in self.style_families)}")
        if self.product_integration:
            parts.append(f"Product: {self.product_integration}")
        if self.people_guidance:
            parts.append(f"People: {self.people_guidance}")
        if self.brand_integration:
            parts.append(f"Brand presence: {self.brand_integration}")
        if self.regional_cues:
            parts.append(f"Regional cues: {', '.join(self.regional_cues)}")
        if self.reference_characteristics:
            parts.append(f"Visual qualities: {', '.join(self.reference_characteristics)}")
        if self.text_safe_area:
            parts.append(f"Leave clear: {self.text_safe_area}")
        return "\n".join(parts)

    def negative_text(self) -> str:
        """Everything that must not appear, as one neutral line.

        `no_text_in_image` is always expressed. A model that writes the
        headline for us has produced an unusable plate, not a bonus.
        """
        items: list[str] = []
        if self.negative_constraints.no_text_in_image:
            items.append("any text, lettering, words, captions or watermarks")
        items.extend(self.negative_constraints.forbidden_elements)
        items.extend(f"the claim '{claim}'" for claim in self.negative_constraints.forbidden_text)
        items.extend(f"{style} styling" for style in self.negative_constraints.avoid_styles)
        return ", ".join(items)


class ModelPrompt(DomainModel):
    """A canonical prompt rendered for one provider and model.

    `parameters` holds provider-specific knobs. They are opaque here by design:
    the adapter owns their meaning, and nothing outside `app/providers/` may
    read them.
    """

    id: Id = Field(default_factory=new_id)
    campaign_id: Id
    canonical_prompt_id: Id
    specification_id: Id
    specification_version: int = Field(default=1, ge=1)
    provider: str
    model: str
    version: int = Field(default=1, ge=1)

    text: str = Field(min_length=1)
    negative_text: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    aspect_ratio: str = "1:1"
    #: Set when a human edits a compiled prompt. The specification stays
    #: authoritative for the *next* compile; the edit is not promoted into it.
    edited_by_user: bool = False

    def trace(self) -> str:
        """One line naming everything this prompt descends from."""
        return (
            f"campaign {self.campaign_id} · specification {self.specification_id}"
            f" v{self.specification_version} · {self.provider}/{self.model}"
            f" · prompt v{self.version}"
        )


def aspect_ratio_value(ratio: str) -> float:
    """`"16:9"` -> 1.777…  An unparseable ratio is treated as square rather
    than raising: a malformed ratio must not be able to fail a generation."""
    width, _, height = ratio.partition(":")
    try:
        return float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        return 1.0


def nearest_aspect_ratio(ratio: str, supported: tuple[str, ...]) -> str:
    """The closest frame a provider actually accepts.

    Every provider supports a different set, and a ratio one step away from
    what was asked is far better than a request the provider rejects outright.
    """
    if ratio in supported:
        return ratio
    if not supported:
        return ratio
    target = aspect_ratio_value(ratio)
    return min(supported, key=lambda candidate: abs(target - aspect_ratio_value(candidate)))


def fingerprint(payload: dict[str, Any]) -> str:
    """Stable digest of the fields a prompt was compiled from.

    Sorted keys and a fixed separator, so the same specification always
    produces the same digest — the property the reproducibility test rests on.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
