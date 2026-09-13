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

_PREAMBLE = (
    "Generate a photographic advertising plate — the background visual only, "
    "with no text of any kind rendered in the image."
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
