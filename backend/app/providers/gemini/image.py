"""Gemini image generation — a remote API call, never a local model.

Uses the Interactions API — `client.aio.interactions.create(...)` with a
`response_format` of type `image` — which is the shape the current Gemini API
documentation and the installed `google-genai` SDK both describe. Every field
sent here (`model`, `input`, `response_format.mime_type`, `.aspect_ratio`,
`.image_size`) is documented; nothing undocumented is guessed at.

**Nothing is generated on this machine.** There are no weights on disk, no
local inference, no GPU work. The application server builds a request, sends
it, and receives bytes. That is the whole of the image pipeline's compute
story, and it is why the only way to make an image is to have a working
credential and a billed account.

**The model produces a plate, never a poster** (ADR-006). It is asked for a
photographic background with no lettering in it; the headline, call to action,
logo, colours and safe areas are drawn afterwards by the deterministic Pillow
renderer. Nothing here may ask the model to set brand text.

**Format is detected, never assumed.** The request asks for JPEG because that
is what the image models accept, but the returned bytes are sniffed and the
recorded MIME type is what actually came back — `image/png`, `image/jpeg` or
`image/webp`. A row that claims PNG over JPEG bytes misleads every tool that
trusts it.

**Retries are billable, so they are rare and narrow.** Only a timeout, a rate
limit or a 5xx is retried, at most `IMAGE_MAX_RETRIES` times (one by default).
A refusal, a bad request or an unusable payload is returned immediately: those
cost money to be told the same thing twice.

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
import time
from typing import Any

from app.config import Settings
from app.logging import get_logger
from app.providers.base import (
    GeneratedImage,
    ImageRef,
    ImageRequest,
    ProviderError,
    ProviderInvalidResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.errors import translate
from app.providers.gemini.prompt import GEMINI_ASPECT_RATIOS

log = get_logger(__name__)

#: The only response mime type the Gemini image models accept. Asking for
#: `image/png` is refused outright — *"The value 'image/png' is not supported
#: for 'response_format.mime_type'. Supported values: 'image/jpeg'"* — so this
#: is the provider's constraint, not a quality choice. It is deliberately not
#: a setting: a knob whose only legal value is its default is a knob that
#: exists to be set wrongly.
#:
#: This governs the *plate only*. Deterministic rendering stays PNG — the
#: renderer defaults to it and composition is lossless (ADR-006, ADR-014).
RESPONSE_MIME_TYPE = "image/jpeg"

#: Formats the pipeline can read back. The request asks for JPEG, but what is
#: recorded is what arrived: the provider is free to change what it returns,
#: and Pillow reads all three.
SUPPORTED_MIME_TYPES: tuple[str, ...] = ("image/png", "image/jpeg", "image/webp")

#: Magic bytes, so the format is read from the payload rather than from a
#: header the provider may omit or get wrong.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)

#: Documented image sizes for the Gemini image models.
IMAGE_SIZES: tuple[str, ...] = ("512px", "1K", "2K", "4K")
_DEFAULT_IMAGE_SIZE = "2K"

#: Reference images the Gemini 3 models accept in one request, per the current
#: documentation. More are dropped rather than sent, because a request the
#: provider rejects wholesale costs the same as one it fulfils.
MAX_REFERENCE_IMAGES = 14

#: The noun the user sees in a translated error. Classification is shared
#: with the other Gemini adapters (`errors.py`); only the wording is local.
_SUBJECT = "The image service"


class GeminiImageProvider:
    """Image generation through the Gemini API."""

    name = "gemini"
    supported_aspect_ratios = GEMINI_ASPECT_RATIOS

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._model = settings.gemini_image_model
        self._timeout = settings.generation_timeout_s
        self._max_retries = settings.image_max_retries
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
        aspect_ratio = _aspect_ratio(request.aspect_ratio)
        image_size = _image_size(request.parameters)
        response_format: dict[str, Any] = {
            "type": "image",
            "mime_type": RESPONSE_MIME_TYPE,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }
        body: dict[str, Any] = {
            "model": self._model,
            "input": _input(request),
            "response_format": response_format,
        }

        started = time.monotonic()
        interaction = await self._call_with_retries(client, body)
        latency_ms = int((time.monotonic() - started) * 1000)

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
        mime_type = _sniff(data, declared=getattr(image, "mime_type", None))
        width, height = _dimensions(data)
        request_id = getattr(interaction, "id", None)

        log.info(
            "gemini_image_generated",
            model=self._model,
            request_id=request_id,
            latency_ms=latency_ms,
            mime_type=mime_type,
            width=width,
            height=height,
            bytes=len(data),
        )
        return [
            GeneratedImage(
                data=data,
                mime_type=mime_type,
                width=width,
                height=height,
                seed=request.seed,
                provider_job_id=request_id,
                # Provenance. Safe metadata only: what produced it and how
                # long it took, never the payload and never a credential.
                metadata={
                    "provider": self.name,
                    "model": getattr(interaction, "model", self._model),
                    "status": str(getattr(interaction, "status", "") or ""),
                    "resolution": str(getattr(image, "resolution", "") or ""),
                    "request_id": request_id or "",
                    "latency_ms": latency_ms,
                    "requested_aspect_ratio": aspect_ratio,
                    "requested_image_size": image_size,
                    "requested_mime_type": RESPONSE_MIME_TYPE,
                    "returned_mime_type": mime_type,
                    "reference_images": len(_usable_references(request)),
                },
            )
        ]

    async def _call_with_retries(self, client: Any, body: dict[str, Any]) -> Any:
        """One call, plus at most `image_max_retries` retryable attempts.

        Every attempt is billable, so the loop is deliberately short and only
        a failure that could plausibly resolve itself is repeated.
        """
        attempts = self._max_retries + 1
        last: ProviderError | None = None

        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.wait_for(
                    client.aio.interactions.create(**body), timeout=self._timeout
                )
            except TimeoutError as exc:
                last = ProviderTimeout(
                    "The image service did not respond in time.",
                    detail=f"exceeded {self._timeout}s on attempt {attempt}",
                    provider=self.name,
                    retryable=True,
                )
                last.__cause__ = exc
            except ProviderError as exc:
                last = exc
            except Exception as exc:  # noqa: BLE001 — the vendor's tree stops here
                last = translate(exc, provider=self.name, subject=_SUBJECT)
                last.__cause__ = exc

            if not last.retryable or attempt == attempts:
                raise last
            log.warning(
                "gemini_image_retry",
                model=self._model,
                attempt=attempt,
                of=attempts,
                code=last.code,
            )

        raise (
            last
            if last is not None
            else ProviderUnavailable(  # pragma: no cover
                "The image service could not be reached.", provider=self.name
            )
        )

    async def health(self) -> bool:
        """Cheap reachability: is this adapter configured at all?

        Deliberately not a live call — a health probe that generated an image
        would charge for every check.
        """
        return bool(self._api_key or self._client)


def _input(request: ImageRequest) -> str | list[dict[str, Any]]:
    """The interaction input: the instruction, or content blocks when there
    are reference images.

    References are *guidance*, never something to reproduce. What reaches this
    point has already been through Reference Intelligence, whose schema has
    nowhere to put quoted text, a logo or a layout (ADR-011) — so the image
    itself is passed for its light, palette and composition, and the prompt
    carries the instruction that says so.
    """
    references = _usable_references(request)
    if not references:
        return _instruction(request)
    blocks: list[dict[str, Any]] = [_image_block(image) for image in references]
    blocks.append({"type": "text", "text": _instruction(request)})
    return blocks


def _usable_references(request: ImageRequest) -> tuple[ImageRef, ...]:
    """Reference images this adapter can actually send.

    A ref carrying only a storage key is skipped rather than fatal: the
    provider layer has no storage, and a missing piece of *guidance* should
    not fail a generation the way a missing subject would.
    """
    usable = tuple(ref for ref in request.reference_images if ref.data)
    if len(usable) > MAX_REFERENCE_IMAGES:
        log.warning(
            "gemini_reference_images_trimmed",
            given=len(usable),
            sent=MAX_REFERENCE_IMAGES,
        )
        return usable[:MAX_REFERENCE_IMAGES]
    return usable


def _image_block(image: ImageRef) -> dict[str, Any]:
    assert image.data is not None  # guaranteed by `_usable_references`
    return {
        "type": "image",
        "data": base64.b64encode(image.data).decode("ascii"),
        "mime_type": image.mime_type,
    }


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


def _sniff(data: bytes, *, declared: str | None) -> str:
    """The format of the bytes, read from the bytes.

    The provider's own header is used only to tell WebP apart, and only when
    the payload agrees it is a RIFF container. Trusting a declared type we
    cannot corroborate is how a row ends up describing something it is not.
    """
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if declared in SUPPORTED_MIME_TYPES:
        return declared
    raise ProviderInvalidResponse(
        "The image service returned an image in a format we cannot read.",
        detail=f"declared={declared!r}, first bytes={data[:8]!r}",
        provider="gemini",
    )


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
