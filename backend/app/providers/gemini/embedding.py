"""Gemini text embeddings for the Brand Brain.

Uses `client.aio.models.embed_content(...)`, which is the current documented
embedding call in the `google-genai` SDK. Width is requested explicitly with
`output_dimensionality`, so the API returns vectors of exactly the width
`brand_chunks.embedding` is declared at. **Nothing is truncated here.** A
vector that comes back the wrong length is a configuration error and is
reported as one — silently trimming it would turn a misconfiguration into
retrieval that is merely bad, which is far harder to diagnose (ROADMAP R-4).

Vectors are L2-normalised on the way out. The Gemini documentation states that
`gemini-embedding-001` output must be normalised manually whenever the
requested width is not the model's native 3072, and normalising an already
unit-length vector is a no-op — so doing it unconditionally is correct for
every model and does not depend on matching a model name.

`task_type` is `SEMANTIC_SIMILARITY`: the `EmbeddingProvider` protocol has one
`embed()` used for both stored chunks and live queries, and a symmetric task
type is the correct choice when one encoder produces both sides of the
comparison. Asking for `RETRIEVAL_DOCUMENT` here would embed queries as
documents.

**Credentials are server-side only**, and no vendor exception escapes — both
as in the other adapters in this package. The test suite runs on
`EMBEDDING_PROVIDER=mock`; this class is covered by tests driving a fake SDK
client, so no test spends a credit.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from app.config import Settings
from app.providers.base import (
    ProviderError,
    ProviderInvalidResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.errors import translate

#: The noun the user sees in a translated error.
_SUBJECT = "The embedding service"

#: Texts per request. A conservative client-side chunk, not a documented API
#: limit: splitting is always legal, and it keeps one large document from
#: turning into a single request big enough to be rejected whole.
_MAX_BATCH = 100

#: One encoder embeds both stored chunks and live queries, so the symmetric
#: task type is the right one. See the module docstring.
_TASK_TYPE = "SEMANTIC_SIMILARITY"


class GeminiEmbeddingProvider:
    """Text embeddings through the Gemini API."""

    name = "gemini"

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._model = settings.gemini_embedding_model
        #: Declared width. Checked against the pgvector column at startup by
        #: `registry.assert_embedding_dimensions`, and checked again against
        #: what the API actually returns on every call.
        self.dimensions = settings.gemini_embedding_dimensions
        self._timeout = settings.llm_timeout_s
        self._client = client
        self._api_key = settings.gemini_api_key

    def _ensure_client(self) -> Any:
        if self._client is None:
            if not self._api_key:
                raise ProviderUnavailable(
                    "Gemini embeddings are not configured.",
                    detail="GEMINI_API_KEY is unset",
                    provider=self.name,
                )
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            # No request, no spend. A caller with nothing to embed gets an
            # empty list rather than an error, because "embed these zero
            # chunks" is a legitimate thing for a batching loop to ask.
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _MAX_BATCH):
            batch = texts[start : start + _MAX_BATCH]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        client = self._ensure_client()
        from google.genai import types

        try:
            response = await asyncio.wait_for(
                client.aio.models.embed_content(
                    model=self._model,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=_TASK_TYPE,
                        output_dimensionality=self.dimensions,
                    ),
                ),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            raise ProviderTimeout(
                "The embedding service did not respond in time.",
                detail=f"exceeded {self._timeout}s",
                provider=self.name,
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — the vendor's error tree stops here
            raise translate(exc, provider=self.name, subject=_SUBJECT) from exc

        embeddings = getattr(response, "embeddings", None) or []
        if len(embeddings) != len(batch):
            # Vectors are matched to chunks by position. A short reply would
            # pair every later chunk with the wrong text, which reads as a
            # quality problem for as long as nobody suspects the adapter.
            raise ProviderInvalidResponse(
                "The embedding service returned the wrong number of vectors.",
                detail=f"asked for {len(batch)}, received {len(embeddings)}",
                provider=self.name,
            )
        return [self._vector(embedding, index) for index, embedding in enumerate(embeddings)]

    def _vector(self, embedding: Any, index: int) -> list[float]:
        values = getattr(embedding, "values", None)
        if not values:
            raise ProviderInvalidResponse(
                "The embedding service returned an empty vector.",
                detail=f"vector {index} of the batch carried no values",
                provider=self.name,
            )
        if len(values) != self.dimensions:
            raise ProviderInvalidResponse(
                "The embedding service returned vectors of an unexpected width.",
                detail=(
                    f"model {self._model} returned {len(values)} dimensions, "
                    f"configured for {self.dimensions}"
                ),
                provider=self.name,
            )
        return _normalise([float(value) for value in values], provider=self.name, model=self._model)

    async def health(self) -> bool:
        """Cheap reachability, not a live call — see the LLM adapter."""
        return bool(self._api_key or self._client)


def _normalise(vector: list[float], *, provider: str, model: str) -> list[float]:
    """Scale to unit length so cosine distance behaves."""
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # A zero vector has no direction; cosine distance against it is
        # undefined, and storing one would poison every later search.
        raise ProviderInvalidResponse(
            "The embedding service returned a vector with no direction.",
            detail=f"model {model} returned an all-zero vector",
            provider=provider,
        )
    return [value / norm for value in vector]
