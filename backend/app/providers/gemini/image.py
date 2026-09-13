"""Gemini image generation.

Uses the Interactions API — `client.aio.interactions.create(...)` with a
`response_format` of type `image` — which is the shape the current Gemini API
documentation and the installed `google-genai` SDK both describe. Every field
sent here (`model`, `input`, `response_format.mime_type`, `.aspect_ratio`,
`.image_size`) is documented; nothing undocumented is guessed at.

**Credentials are server-side only.** The key is read from `Settings`, which
reads it from the environment. It never appears in a response, a log line, an
error message or anything that reaches the browser.

**No vendor exception escapes.** Everything becomes a `ProviderError` subclass
carrying a message safe to show a user, with the vendor's own words kept in
`detail` for the log. A caller handles five cases, not the SDK's error tree.

This adapter is never exercised automatically: the test suite runs on
`IMAGE_PROVIDERS=mock`, and reaching Gemini requires deliberately configuring
it. Its behaviour is covered by tests that drive a fake SDK client through this
same class, so the mapping from provider outcome to typed error is verified
without spending a credit.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from typing import Any

from app.config import Settings
from app.logging import get_logger
from app.providers.base import (
    ContentBlocked,
    GeneratedImage,
    ImageRequest,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.prompt import GEMINI_ASPECT_RATIOS

log = get_logger(__name__)

#: Documented image sizes for the Gemini image models.
IMAGE_SIZES: tuple[str, ...] = ("512px", "1K", "2K", "4K")
_DEFAULT_IMAGE_SIZE = "2K"

#: Substrings that identify a safety refusal in an otherwise ordinary client
#: error. A refusal is a product event — the UI offers a revision — rather than
#: a bug, so it must not be reported as a generic provider failure.
_BLOCKED_MARKERS = ("safety", "blocked", "prohibited_content", "policy")


class GeminiImageProvider:
    """Image generation through the Gemini API."""

    name = "gemini"
    supported_aspect_ratios = GEMINI_ASPECT_RATIOS

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._model = settings.gemini_image_model
        self._timeout = settings.generation_timeout_s
        # Injected in tests. Built lazily otherwise so importing this module
        # never requires a key — the registry imports adapters lazily too, but
        # a constructor that reached for credentials would still break
        # `--collect-only` on a machine with none.
        self._client = client
        self._api_key = settings.gemini_api_key

    def _ensure_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable(
                    "Gemini image generation is not configured.",
                    detail="GEMINI_API_KEY is unset",
                    provider=self.name,
                )
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def generate(self, request: ImageRequest) -> list[GeneratedImage]:
        client = self._ensure_client()
        response_format: dict[str, Any] = {
            "type": "image",
            "mime_type": "image/png",
            "aspect_ratio": _aspect_ratio(request.aspect_ratio),
            "image_size": _image_size(request.parameters),
        }

        try:
            interaction = await asyncio.wait_for(
                client.aio.interactions.create(
                    model=self._model,
                    input=_instruction(request),
                    response_format=response_format,
                ),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeout(
                "The image service did not respond in time.",
                detail=f"exceeded {self._timeout}s",
                provider=self.name,
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — the vendor's error tree stops here
            raise _translate(exc, provider=self.name) from exc

        image = getattr(interaction, "output_image", None)
        if image is None or not getattr(image, "data", None):
            # A response with no image is a failure even when the call
            # "succeeded": a caller may rely on never receiving an empty list.
            raise ProviderInvalidResponse(
                "The image service returned no image.",
                detail=f"status={getattr(interaction, 'status', 'unknown')}",
                provider=self.name,
            )

        data = _decode(image.data)
        width, height = _dimensions(data)
        return [
            GeneratedImage(
                data=data,
                mime_type=getattr(image, "mime_type", None) or "image/png",
                width=width,
                height=height,
                seed=request.seed,
                provider_job_id=getattr(interaction, "id", None),
                # Safe metadata only: what produced it, never the payload and
                # never anything carrying a credential.
                metadata={
                    "model": getattr(interaction, "model", self._model),
                    "status": str(getattr(interaction, "status", "") or ""),
                    "resolution": str(getattr(image, "resolution", "") or ""),
                },
            )
        ]

    async def health(self) -> bool:
        """Cheap reachability: is this adapter configured at all?

        Deliberately not a live call — a health probe that generated an image
        would charge for every check.
        """
        return bool(self._api_key or self._client)


def _instruction(request: ImageRequest) -> str:
    """The prompt as Gemini receives it.

    The adapter has already folded exclusions into `prompt`; this only appends
    a negative prompt that arrived separately, which happens when a canonical
    prompt is sent through a provider whose adapter kept them apart.
    """
    if request.negative_prompt and request.negative_prompt not in request.prompt:
        return f"{request.prompt}\n\nDo not include: {request.negative_prompt}."
    return request.prompt


def _aspect_ratio(ratio: str) -> str:
    return ratio if ratio in GEMINI_ASPECT_RATIOS else "1:1"


def _image_size(parameters: dict[str, Any] | None) -> str:
    """Only a documented size reaches the API. An adapter that invented one
    would fail the request at the provider rather than here."""
    requested = (parameters or {}).get("image_size")
    return requested if requested in IMAGE_SIZES else _DEFAULT_IMAGE_SIZE


def _decode(data: Any) -> bytes:
    """Image bytes from the API's base64 payload."""
    if isinstance(data, bytes | bytearray):
        return bytes(data)
    try:
        return base64.b64decode(str(data), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderInvalidResponse(
            "The image service returned an unreadable image.",
            detail=f"base64 decode failed: {type(exc).__name__}",
            provider="gemini",
        ) from exc


def _dimensions(data: bytes) -> tuple[int, int]:
    """Read the real size from the bytes rather than trusting the request.

    The provider may return a frame one step from what was asked, and an asset
    row claiming a size it does not have would mislead every consumer of it.
    """
    import io

    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError) as exc:
        raise ProviderInvalidResponse(
            "The image service returned something that is not an image.",
            detail=type(exc).__name__,
            provider="gemini",
        ) from exc


def _translate(exc: Exception, *, provider: str) -> ProviderError:
    """Vendor exception -> typed provider error.

    The vendor's message goes to `detail`, which is log-side only; the user
    sees a sentence that tells them what to do next.
    """
    status = _status_of(exc)
    text = str(exc).lower()
    detail = f"{type(exc).__name__}: {exc}"[:500]

    if status == 429 or "rate limit" in text or "quota" in text:
        return ProviderRateLimited(
            "The image service is rate limited. Try again shortly.",
            detail=detail,
            provider=provider,
        )
    if any(marker in text for marker in _BLOCKED_MARKERS):
        return ContentBlocked(
            "The image service refused this request on safety grounds.",
            detail=detail,
            provider=provider,
        )
    if status is not None and status >= 500:
        return ProviderUnavailable(
            "The image service is temporarily unavailable.", detail=detail, provider=provider
        )
    if status in (401, 403):
        # Never echoes the key, and never tells a user to go and find it.
        return ProviderUnavailable(
            "The image service rejected this workspace's credentials.",
            detail=detail,
            provider=provider,
        )
    if status is not None and 400 <= status < 500:
        return ProviderInvalidResponse(
            "The image service could not process this request.",
            detail=detail,
            provider=provider,
        )
    return ProviderUnavailable(
        "The image service could not be reached.", detail=detail, provider=provider
    )


def _status_of(exc: Exception) -> int | None:
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None
