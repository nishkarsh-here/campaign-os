"""Embedding providers: the mock, and the Gemini adapter on a fake SDK client.

Nothing here reaches the network. The dimensionality cases matter most: a
vector of the wrong width is the one failure that does not announce itself —
it either errors on insert or, if anyone ever trimmed it, quietly degrades
every search afterwards (ROADMAP R-4).
"""

from __future__ import annotations

import asyncio
import math

import pytest

from app.config import Settings
from app.db.models import EMBEDDING_DIMENSIONS
from app.providers.base import (
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.embedding import GeminiEmbeddingProvider
from app.providers.mock.embedding import MockEmbeddingProvider
from app.providers.registry import assert_embedding_dimensions

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "gemini_api_key": "test-key",
        "llm_timeout_s": 5,
    }
    return Settings(**{**base, **overrides})


# ------------------------------------------------------------------ the mock
class TestMockProvider:
    async def test_it_produces_the_column_width(self) -> None:
        provider = MockEmbeddingProvider()
        assert provider.dimensions == EMBEDDING_DIMENSIONS
        (vector,) = await provider.embed(["brand guidelines"])
        assert len(vector) == EMBEDDING_DIMENSIONS

    async def test_one_vector_per_text(self) -> None:
        vectors = await MockEmbeddingProvider().embed(["a", "b", "c"])
        assert len(vectors) == 3

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("timeout", ProviderTimeout),
            ("rate_limit", ProviderRateLimited),
            ("unavailable", ProviderUnavailable),
        ],
    )
    async def test_each_failure_mode_raises_its_typed_error(self, mode, expected) -> None:
        with pytest.raises(expected):
            await MockEmbeddingProvider(mode).embed(["text"])


# -------------------------------------------------------- the Gemini adapter
class _Embedding:
    def __init__(self, values) -> None:
        self.values = values


class _Response:
    def __init__(self, embeddings) -> None:
        self.embeddings = embeddings


class _FakeModels:
    """Stands in for `client.aio.models`."""

    def __init__(self, *responses, error: Exception | None = None, delay: float = 0.0) -> None:
        self._responses = list(responses)
        self._error = error
        self._delay = delay
        self.calls: list[dict] = []

    async def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.aio = type("Aio", (), {"models": models})()


def _values(width: int = EMBEDDING_DIMENSIONS, fill: float = 0.5) -> list[float]:
    return [fill] * width


def _response(count: int = 1, width: int = EMBEDDING_DIMENSIONS) -> _Response:
    return _Response([_Embedding(_values(width)) for _ in range(count)])


def _provider(models: _FakeModels, **settings_overrides) -> GeminiEmbeddingProvider:
    return GeminiEmbeddingProvider(_settings(**settings_overrides), client=_FakeClient(models))


class TestGeminiEmbedding:
    async def test_a_single_text_returns_one_vector_of_the_right_width(self) -> None:
        vectors = await _provider(_FakeModels(_response(1))).embed(["brand guidelines"])
        assert len(vectors) == 1
        assert len(vectors[0]) == EMBEDDING_DIMENSIONS

    async def test_a_batch_returns_one_vector_per_text_in_one_call(self) -> None:
        models = _FakeModels(_response(3))
        vectors = await _provider(models).embed(["a", "b", "c"])
        assert len(vectors) == 3
        assert len(models.calls) == 1
        assert models.calls[0]["contents"] == ["a", "b", "c"]

    async def test_the_width_is_requested_not_trimmed_afterwards(self) -> None:
        """The API is told what width to produce. Business logic never cuts a
        vector down — that would turn a misconfiguration into bad retrieval."""
        models = _FakeModels(_response(1))
        await _provider(models).embed(["text"])
        config = models.calls[0]["config"]
        assert config.output_dimensionality == EMBEDDING_DIMENSIONS
        assert config.task_type == "SEMANTIC_SIMILARITY"
        assert models.calls[0]["model"] == "gemini-embedding-001"

    async def test_vectors_come_back_normalised(self) -> None:
        """`gemini-embedding-001` output must be normalised manually whenever
        the requested width is not the model's native 3072."""
        (vector,) = await _provider(_FakeModels(_response(1))).embed(["text"])
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)

    async def test_a_large_batch_is_split_across_requests(self) -> None:
        models = _FakeModels(_response(100), _response(20))
        vectors = await _provider(models).embed([f"chunk {i}" for i in range(120)])
        assert len(vectors) == 120
        assert [len(call["contents"]) for call in models.calls] == [100, 20]

    async def test_empty_input_returns_nothing_and_spends_nothing(self) -> None:
        models = _FakeModels(_response(1))
        assert await _provider(models).embed([]) == []
        assert models.calls == []

    async def test_declared_dimensions_match_the_column(self) -> None:
        """The startup guard is only meaningful if the adapter declares the
        width it actually asks for."""
        provider = _provider(_FakeModels(_response(1)))
        assert provider.dimensions == EMBEDDING_DIMENSIONS
        assert_embedding_dimensions(provider)


class TestGeminiDimensionMismatch:
    async def test_a_wrong_width_is_reported_not_truncated(self) -> None:
        models = _FakeModels(_response(1, width=3072))
        with pytest.raises(ProviderInvalidResponse) as caught:
            await _provider(models).embed(["text"])
        assert "width" in caught.value.message

    async def test_a_configured_width_the_column_cannot_hold_fails_at_startup(self) -> None:
        provider = _provider(_FakeModels(_response(1)), gemini_embedding_dimensions=768)
        with pytest.raises(RuntimeError) as caught:
            assert_embedding_dimensions(provider)
        assert "768" in str(caught.value)
        assert str(EMBEDDING_DIMENSIONS) in str(caught.value)

    async def test_a_configured_width_outside_the_api_range_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _settings(gemini_embedding_dimensions=4096)


class TestGeminiFailures:
    async def test_too_few_vectors_is_an_invalid_response(self) -> None:
        """Vectors are matched to chunks by position; a short reply would pair
        every later chunk with the wrong text."""
        models = _FakeModels(_response(2))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(models).embed(["a", "b", "c"])

    async def test_a_missing_embeddings_field_is_an_invalid_response(self) -> None:
        models = _FakeModels(_Response(None))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(models).embed(["a"])

    async def test_an_empty_vector_is_an_invalid_response(self) -> None:
        models = _FakeModels(_Response([_Embedding([])]))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(models).embed(["a"])

    async def test_an_all_zero_vector_is_refused(self) -> None:
        """A zero vector has no direction; cosine distance against it is
        undefined and it would poison every later search."""
        models = _FakeModels(_Response([_Embedding(_values(fill=0.0))]))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(models).embed(["a"])

    async def test_a_slow_provider_times_out(self) -> None:
        models = _FakeModels(_response(1), delay=0.2)
        provider = GeminiEmbeddingProvider(_settings(llm_timeout_s=0), client=_FakeClient(models))
        with pytest.raises(ProviderTimeout):
            await provider.embed(["a"])

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (type("E429", (Exception,), {"code": 429}), ProviderRateLimited),
            (type("E503", (Exception,), {"code": 503}), ProviderUnavailable),
            (type("E401", (Exception,), {"code": 401}), ProviderUnavailable),
            (type("E400", (Exception,), {"code": 400}), ProviderInvalidResponse),
        ],
    )
    async def test_status_codes_become_typed_errors(self, error, expected) -> None:
        models = _FakeModels(error=error("provider said no"))
        with pytest.raises(expected):
            await _provider(models).embed(["a"])

    async def test_no_vendor_exception_escapes(self) -> None:
        models = _FakeModels(error=KeyError("internal sdk detail"))
        with pytest.raises(ProviderError):
            await _provider(models).embed(["a"])

    async def test_an_unconfigured_provider_says_so(self) -> None:
        provider = GeminiEmbeddingProvider(_settings(gemini_api_key=None))
        with pytest.raises(ProviderUnavailable):
            await provider.embed(["a"])
        assert await provider.health() is False

    async def test_the_key_never_appears_in_a_user_facing_message(self) -> None:
        models = _FakeModels(
            error=type("E", (Exception,), {"code": 401})("invalid api key test-key")
        )
        with pytest.raises(ProviderUnavailable) as caught:
            await _provider(models).embed(["a"])
        assert "test-key" not in caught.value.message
