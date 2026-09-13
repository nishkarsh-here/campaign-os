"""Deterministic offline image generation.

Not a stub that returns a fixed file. It renders a real PNG whose composition
is *derived from the prompt*: the same prompt always produces the same image,
and two different prompts produce visibly different ones. That is what makes
the whole pipeline demonstrable and testable with no network and no spend —
a gallery of identical grey squares would prove only that the plumbing runs.

What it draws is deliberately abstract: bands and a focal shape in colours
taken from the prompt's own palette. It is a *plate stand-in*, and it carries
no text, which is also the rule the real providers are held to (ADR-006).

`failure_mode` drives the same taxonomy as the other mocks, so the failure and
retry paths are exercised without a live provider ever being called.
"""

from __future__ import annotations

import asyncio
import hashlib
import io

from PIL import Image, ImageDraw

from app.providers.base import (
    ContentBlocked,
    GeneratedImage,
    ImageRequest,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

#: The frames the mock renders. Matches what the prompt adapters may ask for.
_RATIO_SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1024, 1024),
    "3:4": (896, 1152),
    "4:3": (1152, 896),
    "9:16": (768, 1344),
    "16:9": (1344, 768),
}

#: Used when the prompt names no palette of its own.
_FALLBACK_PALETTE = ("#1F2933", "#3E4C59", "#E4572E", "#F5F5F4")


class MockImageProvider:
    """Offline image generation with stable, prompt-derived output."""

    name = "mock"
    supported_aspect_ratios = tuple(_RATIO_SIZES)

    def __init__(self, failure_mode: str = "none", *, latency_seconds: float = 0.0) -> None:
        self._failure_mode = failure_mode
        # A demo where three providers all finish instantly never shows a
        # RUNNING card. A small configurable delay makes the async job states
        # observable without making the test suite slow (default: none).
        self._latency = latency_seconds

    def _maybe_fail(self) -> None:
        match self._failure_mode:
            case "timeout":
                raise ProviderTimeout("The image service timed out.", provider=self.name)
            case "rate_limit":
                raise ProviderRateLimited("Image rate limit reached.", provider=self.name)
            case "unavailable":
                raise ProviderUnavailable("The image service is unavailable.", provider=self.name)
            case "blocked":
                raise ContentBlocked(
                    "The image request was refused by the safety filter.", provider=self.name
                )
            case "malformed":
                raise ProviderInvalidResponse(
                    "The image service returned no usable image.", provider=self.name
                )

    async def generate(self, request: ImageRequest) -> list[GeneratedImage]:
        self._maybe_fail()
        if self._latency:
            await asyncio.sleep(self._latency)

        width, height = _RATIO_SIZES.get(request.aspect_ratio, _RATIO_SIZES["1:1"])
        seed = request.seed or _digest(request.prompt)
        palette = _palette(request.prompt)

        images: list[GeneratedImage] = []
        for index in range(max(1, request.count)):
            data = _render(width, height, palette, f"{seed}:{index}")
            images.append(
                GeneratedImage(
                    data=data,
                    mime_type="image/png",
                    width=width,
                    height=height,
                    seed=f"{seed}:{index}",
                    provider_job_id=f"mock-{_digest(request.prompt)[:12]}-{index}",
                    metadata={"renderer": "mock", "deterministic": True},
                )
            )
        return images

    async def health(self) -> bool:
        return self._failure_mode == "none"


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode(), digest_size=8).hexdigest()


def _palette(prompt: str) -> list[str]:
    """Hex colours the prompt itself named, else the fallback.

    Reading them out of the prompt is what makes a mock plate recognisably
    *this* campaign's rather than generic — the palette travels from the
    Creative Specification all the way to the pixels.
    """
    found = [
        token
        for token in prompt.replace(",", " ").split()
        if token.startswith("#") and len(token.strip(".")) in (4, 7)
    ]
    return [c.strip(".") for c in found] or list(_FALLBACK_PALETTE)


def _render(width: int, height: int, palette: list[str], seed: str) -> bytes:
    """A deterministic abstract plate.

    Bands plus one focal shape, positioned from the seed. No text of any kind:
    the plate is the visual, and brand type is composited later (ADR-006).
    """
    digest = hashlib.blake2b(seed.encode(), digest_size=16).digest()
    image = Image.new("RGB", (width, height), _rgb(palette[0]))
    draw = ImageDraw.Draw(image)

    bands = 3 + digest[0] % 3
    for index in range(bands):
        colour = _rgb(palette[(index + 1) % len(palette)])
        top = int(height * (index / bands)) + digest[index + 1] % 40
        bottom = int(height * ((index + 1) / bands))
        draw.rectangle([(0, top), (width, bottom)], fill=colour)

    # One focal element, so a viewer can see two plates differ at a glance.
    radius = min(width, height) // (3 + digest[5] % 3)
    centre_x = width // 2 + (digest[6] - 128) * width // 512
    centre_y = height // 2 + (digest[7] - 128) * height // 512
    draw.ellipse(
        [
            (centre_x - radius, centre_y - radius),
            (centre_x + radius, centre_y + radius),
        ],
        fill=_rgb(palette[-1]),
    )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    value = hex_colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except ValueError:
        return (128, 128, 128)
