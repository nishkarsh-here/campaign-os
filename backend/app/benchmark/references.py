"""Building synthetic style references, safely.

Every reference in this benchmark is **abstract style only**. Nothing here
describes a real campaign, and nothing reproduces one: `ReferenceAnalysis` has
no field that could hold quoted copy, a logo, a layout coordinate or a font
family, which is the schema-level enforcement of ADR-011 — learn the style,
never copy the design.

The helper exists because the three companies would otherwise each hand-build
the same nested value objects, and the fields are easy to get subtly wrong:
`dominant_palette` holds hex, while brightness, saturation and contrast are
0-to-1 quantities rather than the words a designer would use. One factory
means one place to be right.
"""

from __future__ import annotations

from app.domain.common import StyleFamily
from app.domain.reference import (
    ColorProfile,
    Composition,
    ImageryStyle,
    LayoutProfile,
    Lighting,
    ReferenceAnalysis,
    VisualDensity,
)

#: What may never be carried across from a reference, restated as prose for
#: the prompt layer. The schema already makes most of it impossible; saying it
#: again is what stops a future field from quietly reopening the door.
NOT_TRANSFERABLE: tuple[str, ...] = (
    "any lettering, headline or caption visible in the frame",
    "logos, wordmarks or packaging graphics",
    "an exact reproducible layout or measured coordinates",
    "identified typeface families",
)


def style_reference(
    *,
    reference_id: str,
    style_families: list[StyleFamily],
    composition: Composition,
    lighting: Lighting,
    imagery_style: list[ImageryStyle],
    palette: list[str],
    brightness: float,
    saturation: float,
    contrast: float,
    temperature: str,
    image_text_balance: str,
    subject_placement: str,
    hierarchy: str,
    density: VisualDensity,
    mood: list[str],
    subject_treatment: str,
    takeaways: list[str],
    summary: str,
    confidence: float = 0.8,
    extra_not_transferable: list[str] | None = None,
) -> ReferenceAnalysis:
    """One abstract style reference, validated against the real schema."""
    return ReferenceAnalysis(
        reference_id=reference_id,
        style_families=style_families,
        composition=composition,
        lighting=lighting,
        imagery_style=imagery_style,
        color=ColorProfile(
            dominant_palette=palette,
            brightness=brightness,
            saturation=saturation,
            contrast=contrast,
            temperature=temperature,
        ),
        layout=LayoutProfile(
            image_text_balance=image_text_balance,
            subject_placement=subject_placement,
            hierarchy=hierarchy,
        ),
        visual_density=density,
        mood=mood,
        subject_treatment=subject_treatment,
        style_takeaways=takeaways,
        not_transferable=[*NOT_TRANSFERABLE, *(extra_not_transferable or [])],
        confidence=confidence,
        summary=summary,
    )
