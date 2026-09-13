"""The mock provider's prompt adapter.

Deliberately the thinnest possible adapter: it emits the canonical rendering
unchanged. That makes it useful as a control — a test that compares a real
adapter against this one is comparing *formatting*, which is the only thing an
adapter is allowed to change (ADR-005).
"""

from __future__ import annotations

from app.domain.prompt import CanonicalPrompt, ModelPrompt, nearest_aspect_ratio

MOCK_ASPECT_RATIOS: tuple[str, ...] = ("1:1", "3:4", "4:3", "9:16", "16:9")


class MockPromptAdapter:
    name = "mock"

    def __init__(self, model: str = "mock-image-1") -> None:
        self.model = model
        self.supported_aspect_ratios = MOCK_ASPECT_RATIOS

    def compile(self, canonical: CanonicalPrompt, *, version: int = 1) -> ModelPrompt:
        return ModelPrompt(
            campaign_id=canonical.campaign_id,
            canonical_prompt_id=canonical.id,
            specification_id=canonical.specification_id,
            specification_version=canonical.specification_version,
            provider=self.name,
            model=self.model,
            version=version,
            text=canonical.render(),
            negative_text=canonical.negative_text() or None,
            aspect_ratio=nearest_aspect_ratio(canonical.aspect_ratio, MOCK_ASPECT_RATIOS),
        )
