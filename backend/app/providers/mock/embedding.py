"""Deterministic mock embeddings.

Not random noise. This uses the hashing trick over word tokens, so cosine
similarity between two vectors reflects genuine **lexical** overlap. That
matters: a retrieval test built on random vectors proves only that the
plumbing runs, whereas this one can assert that querying "prohibited claims"
actually ranks the chunk about prohibited claims first.

It is not semantic — "car" and "automobile" are unrelated here — and that limit
is deliberate and documented rather than papered over.
"""

from __future__ import annotations

import hashlib
import math
import re

from app.db.models import EMBEDDING_DIMENSIONS
from app.providers.base import (
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)

_TOKEN = re.compile(r"[a-z0-9]+")
#: Two hashes per token spreads collisions, the standard signed-hashing trick.
_HASHES = 2


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _bucket(token: str, salt: int) -> tuple[int, float]:
    digest = hashlib.blake2b(f"{salt}:{token}".encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    # Signed hashing: the sign bit keeps unrelated collisions from always
    # reinforcing each other.
    return value % EMBEDDING_DIMENSIONS, 1.0 if (value >> 63) & 1 else -1.0


class MockEmbeddingProvider:
    """Offline embeddings with stable, meaningful geometry."""

    name = "mock"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, failure_mode: str = "none") -> None:
        self._failure_mode = failure_mode

    def _maybe_fail(self) -> None:
        match self._failure_mode:
            case "timeout":
                raise ProviderTimeout("The embedding service timed out.", provider=self.name)
            case "rate_limit":
                raise ProviderRateLimited("Embedding rate limit reached.", provider=self.name)
            case "unavailable":
                raise ProviderUnavailable(
                    "The embedding service is unavailable.", provider=self.name
                )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._maybe_fail()
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        tokens = _tokens(text)
        if not tokens:
            # A zero vector has no direction; cosine distance against it is
            # undefined. Anchor empty input to one fixed basis vector instead.
            vector[0] = 1.0
            return vector

        # Sub-linear term weighting, so one repeated word cannot dominate.
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            weight = 1.0 + math.log(count)
            for salt in range(_HASHES):
                index, sign = _bucket(token, salt)
                vector[index] += sign * weight

        norm = math.sqrt(sum(v * v for v in vector))
        return [v / norm for v in vector] if norm else vector
