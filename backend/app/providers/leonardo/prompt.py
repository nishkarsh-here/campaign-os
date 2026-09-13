"""Leonardo's rendering of a canonical prompt.

Leonardo takes a comma-delimited descriptor list rather than prose, and has a
real `negative_prompt` field — so the exclusions stay out of the main prompt
instead of being folded into it as they must be for Gemini. Same canonical
input, same creative meaning, different packaging (ADR-005).

The adapter exists in Milestone 6 even though no Leonardo *image* provider does:
it is the second implementation that proves the prompt abstraction is real
rather than a Gemini-shaped interface with one caller. Adding fal.ai later is
then a file, not a refactor.
"""

from __future__ import annotations

from app.domain.prompt import CanonicalPrompt, ModelPrompt, nearest_aspect_ratio

#: Leonardo works from fixed frames rather than arbitrary ratios.
LEONARDO_ASPECT_RATIOS: tuple[str, ...] = ("1:1", "3:4", "4:3", "9:16", "16:9")


class LeonardoPromptAdapter:
    """`CanonicalPrompt` -> a Leonardo descriptor list."""

    name = "leonardo"

    def __init__(self, model: str) -> None:
        self.model = model
        self.supported_aspect_ratios = LEONARDO_ASPECT_RATIOS

    def compile(self, canonical: CanonicalPrompt, *, version: int = 1) -> ModelPrompt:
        descriptors: list[str] = [
            canonical.subject,
            canonical.environment,
            canonical.composition,
            canonical.lighting,
        ]
        if canonical.focal_point:
            descriptors.append(f"focus on {canonical.focal_point}")
        if canonical.camera:
            descriptors.append(canonical.camera)
        if canonical.color_direction:
            descriptors.append(canonical.color_direction)
        descriptors.extend(canonical.mood)
        descriptors.extend(s.value.replace("_", " ") for s in canonical.style_families)
        descriptors.extend(canonical.reference_characteristics)
        if canonical.text_safe_area:
            descriptors.append("clear negative space for later typography")

        return ModelPrompt(
            campaign_id=canonical.campaign_id,
            canonical_prompt_id=canonical.id,
            specification_id=canonical.specification_id,
            specification_version=canonical.specification_version,
            provider=self.name,
            model=self.model,
            version=version,
            text=", ".join(d.strip().rstrip(".") for d in descriptors if d.strip()),
            negative_text=canonical.negative_text() or None,
            parameters={"alchemy": True, "num_images": 1},
            aspect_ratio=nearest_aspect_ratio(canonical.aspect_ratio, LEONARDO_ASPECT_RATIOS),
        )
