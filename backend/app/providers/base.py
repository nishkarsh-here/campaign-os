"""Provider interfaces.

Five capabilities the product needs from the outside world. Each is a
`typing.Protocol`: implementations do not inherit, they simply match, which
keeps adapters free of our base classes and keeps test doubles trivial.

Two rules every implementation obeys:

* **Errors are typed.** Vendor exceptions never escape an adapter; they become
  `ProviderError` subclasses carrying a user-safe message. Callers handle four
  cases, not forty.
* **Timeouts and retries live here.** Nodes never implement backoff. One place
  to reason about spend, latency and rate limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

from app.domain.prompt import CanonicalPrompt, ModelPrompt

TModel = TypeVar("TModel", bound=BaseModel)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
#: Things that must never reach a log line, matched by shape rather than by
#: value. Pattern-based on purpose: this cannot be handed the actual secrets
#: (nothing in `providers/` reads configuration), and a rule that only redacts
#: the keys we remembered to pass in is a rule that fails on the one we forgot.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # `key=...`, `api_key: ...`, `authorization: Bearer ...`, in a URL or a dict
    re.compile(
        r"((?:api[-_]?key|access[-_]?token|authorization|bearer|secret|password)"
        r"[\"'\s:=]+)([A-Za-z0-9._\-]{8,})",
        re.IGNORECASE,
    ),
    # Google API keys have a fixed, recognisable shape.
    re.compile(r"\bAIza[0-9A-Za-z._\-]{20,}"),
)


def redact_secrets(text: str) -> str:
    """Strip anything key-shaped out of a vendor string.

    Vendor exceptions sometimes quote the request that produced them, and for
    providers that authenticate by query parameter that request contains the
    key. `detail` is log-side only, but "only in the logs" is not a reason for
    a credential to be there.
    """
    redacted = _SECRET_PATTERNS[0].sub(r"\1[redacted]", text)
    return _SECRET_PATTERNS[1].sub("[redacted]", redacted)


class ProviderError(Exception):
    """Base for every provider failure. Carries a message safe to show a user."""

    code = "PROVIDER_ERROR"

    def __init__(self, message: str, *, detail: str | None = None, provider: str = "") -> None:
        super().__init__(message)
        self.message = message
        # Redacted here rather than at each call site: this is the one place
        # every adapter's vendor detail passes through, so it is the only place
        # the guarantee can actually be made.
        self.detail = redact_secrets(detail) if detail else detail  # log-side only
        self.provider = provider


class ProviderTimeout(ProviderError):
    code = "PROVIDER_TIMEOUT"


class ProviderRateLimited(ProviderError):
    code = "PROVIDER_RATE_LIMITED"


class ProviderUnavailable(ProviderError):
    code = "PROVIDER_UNAVAILABLE"


class ProviderInvalidResponse(ProviderError):
    """The call succeeded but the payload could not be used — most often a
    model returning malformed or schema-violating JSON (ADR-009)."""

    code = "PROVIDER_INVALID_RESPONSE"


class ContentBlocked(ProviderError):
    """The provider's safety system refused. A product event, not a bug: the
    UI explains it and offers a revision."""

    code = "CONTENT_BLOCKED"


# --------------------------------------------------------------------------
# Value objects
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ImageRef:
    """An image handed to a provider. Exactly one of `storage_key` / `data`."""

    storage_key: str | None = None
    data: bytes | None = None
    mime_type: str = "image/png"


@dataclass(frozen=True)
class GeneratedImage:
    """A provider's output, before it is persisted."""

    data: bytes
    mime_type: str
    width: int
    height: int
    seed: str | None = None
    provider_job_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ImageRequest:
    """Everything a provider needs. Deliberately provider-neutral: the adapter
    translates, so adding a provider never changes a caller."""

    prompt: str
    negative_prompt: str | None = None
    aspect_ratio: str = "1:1"
    count: int = 1
    seed: str | None = None
    reference_images: tuple[ImageRef, ...] = ()
    #: Adapter-specific knobs. Opaque to callers by design.
    parameters: dict[str, Any] | None = None
    #: Retry-safe. The same key must never produce a second charge.
    idempotency_key: str | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    score: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class StoredFile:
    storage_key: str
    mime_type: str
    bytes_written: int


# --------------------------------------------------------------------------
# Protocols
# --------------------------------------------------------------------------
@runtime_checkable
class LLMProvider(Protocol):
    """Text and multimodal reasoning."""

    name: str

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Free-form text. Used only where structure genuinely does not apply."""
        ...

    async def structured(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str | None = None,
        images: tuple[ImageRef, ...] = (),
        temperature: float = 0.4,
    ) -> TModel:
        """Return a validated instance of `schema`.

        The implementation constrains decoding to the schema, retries on a
        validation failure, and attempts one repair pass before raising
        `ProviderInvalidResponse`. Handling malformed model output once, here,
        is the single highest-value piece of error handling in the system
        (ADR-009) — nodes must never parse JSON themselves.
        """
        ...


@runtime_checkable
class ImageProvider(Protocol):
    """Image generation."""

    name: str
    supported_aspect_ratios: tuple[str, ...]

    async def generate(self, request: ImageRequest) -> list[GeneratedImage]:
        """Generate images, or raise a `ProviderError`. Never returns []
        silently — an empty result is an error, and callers may rely on that."""
        ...

    async def health(self) -> bool:
        """Cheap reachability check. The router uses it to skip a dead provider
        instead of burning the run's time budget discovering it."""
        ...


@runtime_checkable
class PromptAdapter(Protocol):
    """Renders a canonical prompt for one provider and model.

    A Protocol rather than a function so each adapter can carry its own model
    name, parameter defaults and aspect-ratio support. It lives here, beside
    the other provider interfaces, because provider-specific prompt wording is
    provider-specific code — and that never leaves `app/providers/`
    (CLAUDE.md rule 2). Business logic hands over a `CanonicalPrompt` and takes
    back a `ModelPrompt`; it never learns how either provider likes to be asked.

    Adapters reformat. They must not add meaning the canonical prompt does not
    already carry, and they must never mutate the Creative Specification the
    canonical prompt was compiled from (ADR-005).
    """

    name: str
    model: str
    supported_aspect_ratios: tuple[str, ...]

    def compile(self, canonical: CanonicalPrompt, *, version: int = 1) -> ModelPrompt:
        """Render `canonical` for this provider. Pure: same input, same output."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Vector embeddings for the Brand Brain."""

    name: str
    dimensions: int  # asserted against the pgvector column width at startup

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class StorageProvider(Protocol):
    """Binary storage. The browser never addresses storage directly; reads go
    through the API so scope is always checked."""

    name: str

    async def put(self, key: str, data: bytes, *, mime_type: str) -> StoredFile: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(self, key: str, *, expires_in: int = 3600) -> str: ...


@runtime_checkable
class SearchProvider(Protocol):
    """Web/market context. Optional: `NullSearchProvider` returns nothing, and
    market intelligence degrades cleanly (GRAPH_SPEC §2)."""

    name: str

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]: ...


__all__ = [
    "ContentBlocked",
    "EmbeddingProvider",
    "GeneratedImage",
    "ImageProvider",
    "ImageRef",
    "ImageRequest",
    "LLMProvider",
    "PromptAdapter",
    "ProviderError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderTimeout",
    "ProviderUnavailable",
    "RetrievedChunk",
    "SearchProvider",
    "SearchResult",
    "StoredFile",
    "StorageProvider",
]
