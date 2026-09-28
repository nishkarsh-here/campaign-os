"""Gemini's rendering of a canonical prompt.

Gemini's image models take a single natural-language instruction. There is no
separate negative-prompt field in the Interactions API, so everything the plate
must *not* contain has to be folded into the same sentence — which is exactly
the kind of per-provider difference the canonical representation exists to
absorb. The meaning is unchanged; only the packaging is Gemini's (ADR-005).
"""

from __future__ import annotations

from app.domain.prompt import CanonicalPrompt, ModelPrompt, nearest_aspect_ratio

#: Ratios the Gemini image models accept, per the current API documentation.
GEMINI_ASPECT_RATIOS: tuple[str, ...] = (
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
)

#: What we are asking for, before any of the campaign's own content.
#:
#: Craft direction, not campaign truth — which is why it lives in the adapter
#: and not in the compiler (ADR-005). The Canonical Prompt says *what* the
#: picture is of; this says what a good one looks like. Every line of it is
#: about photography, so nothing here can quietly become a creative decision
#: the Creative Specification did not make.
_PREAMBLE = (
    "Generate a premium commercial advertising photograph to be used as a "
    "background plate. Real photography, not illustration: physically "
    "plausible materials, natural shadow falloff, controlled highlights, "
    "believable reflections, and cinematic depth of field with a clear focal "
    "subject. Editorial art direction of the standard expected in a national "
    "campaign — deliberate composition, intentional negative space, and a "
    "strong visual hierarchy."
)

#: The failure modes worth naming outright. A model asked only for "premium"
#: will still hand back a flat vector poster; asked not to, it usually will
#: not. Kept separate from the campaign's own negative constraints so a brand
#: prohibition is never confused with a house style note.
_HOUSE_EXCLUSIONS = (
    "flat vector illustration, generic geometric shapes, decorative gradients, "
    "cartoon or 3D-render styling, presentation-slide layouts, mocked-up user "
    "interfaces, collage, stock-photo cliché, visible watermarks or signatures"
)

#: Restated last because it is the one instruction that must survive
#: everything above it (ADR-006). The plate carries no brand text; the
#: deterministic renderer sets every word.
_NO_TEXT = (
    "Render no text, lettering, numerals, captions, labels, logos or brand "
    "marks anywhere in the image. Type is composited afterwards."
)


class GeminiPromptAdapter:
    """`CanonicalPrompt` -> a Gemini instruction."""

    name = "gemini"

    def __init__(self, model: str) -> None:
        self.model = model
        self.supported_aspect_ratios = GEMINI_ASPECT_RATIOS

    def compile(self, canonical: CanonicalPrompt, *, version: int = 1) -> ModelPrompt:
        negative = canonical.negative_text()
        body = [_PREAMBLE, canonical.render()]
        if negative:
            # Gemini has no negative-prompt parameter, so the exclusions travel
            # in the instruction. Kept as its own paragraph rather than
            # appended to a line, so a long exclusion list cannot be read as
            # part of the scene description.
            body.append(f"Do not include: {negative}.")
        body.append(f"Avoid: {_HOUSE_EXCLUSIONS}.")
        body.append(_NO_TEXT)

        return ModelPrompt(
            campaign_id=canonical.campaign_id,
            canonical_prompt_id=canonical.id,
            specification_id=canonical.specification_id,
            specification_version=canonical.specification_version,
            provider=self.name,
            model=self.model,
            version=version,
            text="\n\n".join(body),
            # Recorded even though it is folded into `text`: it is what the
            # canonical prompt asked for, and a later provider with a real
            # negative field should use it rather than re-derive it.
            negative_text=negative or None,
            parameters={"image_size": "2K"},
            aspect_ratio=nearest_aspect_ratio(canonical.aspect_ratio, GEMINI_ASPECT_RATIOS),
        )
