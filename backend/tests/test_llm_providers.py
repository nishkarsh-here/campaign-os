"""LLM providers: the mock, and the Gemini adapter driven by a fake SDK.

No test here reaches the network and no test spends a credit. The Gemini cases
construct the adapter with an injected client, so every branch of the
outcome-to-typed-error mapping — and the whole structured-output contract of
ADR-009 — is verified offline.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from pydantic import BaseModel, Field

from app.config import Settings
from app.providers.base import (
    ContentBlocked,
    ImageRef,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.llm import GeminiLLMProvider
from app.providers.mock.llm import MockLLMProvider

pytestmark = pytest.mark.unit


class Direction(BaseModel):
    """A small stand-in for the real domain schemas: required fields, a
    constrained number, a list — the shapes a model actually gets wrong."""

    angle: str
    confidence: float = Field(ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list)


_PROMPT = "Propose one strategic direction for a facade systems manufacturer."


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "gemini_api_key": "test-key",
        "llm_timeout_s": 5,
    }
    return Settings(**{**base, **overrides})


# ------------------------------------------------------------------ the mock
class TestMockProvider:
    async def test_structured_returns_the_requested_schema(self) -> None:
        result = await MockLLMProvider().structured(_PROMPT, Direction)
        assert isinstance(result, Direction)

    async def test_the_same_prompt_gives_the_same_object(self) -> None:
        provider = MockLLMProvider()
        first = await provider.structured(_PROMPT, Direction)
        second = await provider.structured(_PROMPT, Direction)
        assert first == second

    async def test_complete_returns_text(self) -> None:
        assert await MockLLMProvider().complete(_PROMPT)

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("timeout", ProviderTimeout),
            ("rate_limit", ProviderRateLimited),
            ("unavailable", ProviderUnavailable),
            ("malformed", ProviderInvalidResponse),
            ("blocked", ContentBlocked),
        ],
    )
    async def test_each_failure_mode_raises_its_typed_error(self, mode, expected) -> None:
        with pytest.raises(expected):
            await MockLLMProvider(mode).structured(_PROMPT, Direction)


# -------------------------------------------------------- the Gemini adapter
class _FakeInteractions:
    """Stands in for `client.aio.interactions`.

    `results` is consumed one call at a time, so a test can make the first
    reply malformed and the second one good — which is the repair pass.
    """

    def __init__(self, *results, error: Exception | None = None, delay: float = 0.0) -> None:
        self._results = list(results)
        self._error = error
        self._delay = delay
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


class _FakeClient:
    def __init__(self, interactions: _FakeInteractions) -> None:
        self.aio = type("Aio", (), {"interactions": interactions})()


class _Interaction:
    def __init__(self, output_text=None, status="completed", id="int-1") -> None:
        self.output_text = output_text
        self.status = status
        self.id = id


def _valid(**overrides) -> _Interaction:
    body = {"angle": "engineered permanence", "confidence": 0.8, "keywords": ["durable"]}
    return _Interaction(json.dumps({**body, **overrides}))


def _provider(interactions: _FakeInteractions, **settings_overrides) -> GeminiLLMProvider:
    return GeminiLLMProvider(_settings(**settings_overrides), client=_FakeClient(interactions))


class TestGeminiStructuredGeneration:
    async def test_it_returns_a_validated_model_not_a_dict(self) -> None:
        result = await _provider(_FakeInteractions(_valid())).structured(_PROMPT, Direction)
        assert isinstance(result, Direction)
        assert result.angle == "engineered permanence"
        assert result.confidence == 0.8

    async def test_it_constrains_decoding_to_the_schema(self) -> None:
        interactions = _FakeInteractions(_valid())
        await _provider(interactions).structured(_PROMPT, Direction, system="Be terse.")

        (call,) = interactions.calls
        assert call["model"] == "gemini-3.8-flash"
        assert call["system_instruction"] == "Be terse."
        assert call["response_format"]["type"] == "text"
        assert call["response_format"]["mime_type"] == "application/json"
        assert call["response_format"]["schema"] == Direction.model_json_schema()

    async def test_temperature_reaches_the_provider(self) -> None:
        """The protocol takes a temperature; an adapter that dropped it would
        make every caller's setting a lie."""
        interactions = _FakeInteractions(_valid())
        await _provider(interactions).structured(_PROMPT, Direction, temperature=0.15)
        assert interactions.calls[0]["generation_config"]["temperature"] == 0.15

    async def test_plain_completion_sends_no_response_format(self) -> None:
        interactions = _FakeInteractions(_Interaction("a sentence"))
        text = await _provider(interactions).complete(_PROMPT, max_tokens=64)

        assert text == "a sentence"
        (call,) = interactions.calls
        assert "response_format" not in call
        assert call["generation_config"]["max_output_tokens"] == 64


class TestGeminiMultimodal:
    async def test_an_image_is_sent_as_a_content_block(self) -> None:
        interactions = _FakeInteractions(_valid())
        await _provider(interactions).structured(
            _PROMPT,
            Direction,
            images=(ImageRef(data=b"\x89PNG-bytes", mime_type="image/png"),),
        )

        blocks = interactions.calls[0]["input"]
        assert [block["type"] for block in blocks] == ["image", "text"]
        assert base64.b64decode(blocks[0]["data"]) == b"\x89PNG-bytes"
        assert blocks[0]["mime_type"] == "image/png"
        assert blocks[1]["text"] == _PROMPT

    async def test_without_images_the_input_is_a_plain_string(self) -> None:
        interactions = _FakeInteractions(_valid())
        await _provider(interactions).structured(_PROMPT, Direction)
        assert interactions.calls[0]["input"] == _PROMPT

    async def test_an_image_passed_by_key_is_refused_not_dropped(self) -> None:
        """The provider layer has no storage. Sending the request without the
        image would produce a confident answer about nothing."""
        interactions = _FakeInteractions(_valid())
        with pytest.raises(ProviderError):
            await _provider(interactions).structured(
                _PROMPT, Direction, images=(ImageRef(storage_key="assets/x.png"),)
            )
        assert interactions.calls == []


class TestGeminiMalformedOutput:
    async def test_one_repair_pass_recovers_a_bad_first_reply(self) -> None:
        interactions = _FakeInteractions(_Interaction("{ not json at all"), _valid())
        result = await _provider(interactions).structured(_PROMPT, Direction)

        assert isinstance(result, Direction)
        assert len(interactions.calls) == 2
        assert "did not validate" in interactions.calls[1]["input"]
        # A repair that wanders is not a repair.
        assert interactions.calls[1]["generation_config"]["temperature"] == 0.0

    async def test_unparseable_json_twice_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction("not json"))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).structured(_PROMPT, Direction)
        assert len(interactions.calls) == 2

    async def test_a_schema_violation_twice_is_an_invalid_response(self) -> None:
        """Valid JSON that is the wrong shape. `confidence` is out of range,
        so nothing is repairable by parsing harder."""
        interactions = _FakeInteractions(_valid(confidence=9.9))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_nothing_is_silently_coerced(self) -> None:
        """A missing required field must not become a default."""
        interactions = _FakeInteractions(_Interaction(json.dumps({"confidence": 0.5})))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_an_empty_reply_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction(""))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_a_whitespace_only_reply_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction("   \n  "))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).complete(_PROMPT)


class TestGeminiFailures:
    async def test_a_slow_provider_times_out(self) -> None:
        interactions = _FakeInteractions(_valid(), delay=0.2)
        provider = GeminiLLMProvider(_settings(llm_timeout_s=0), client=_FakeClient(interactions))
        with pytest.raises(ProviderTimeout):
            await provider.structured(_PROMPT, Direction)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (type("E429", (Exception,), {"code": 429}), ProviderRateLimited),
            (type("E503", (Exception,), {"code": 503}), ProviderUnavailable),
            (type("E401", (Exception,), {"code": 401}), ProviderUnavailable),
            (type("E403", (Exception,), {"code": 403}), ProviderUnavailable),
            (type("E400", (Exception,), {"code": 400}), ProviderInvalidResponse),
        ],
    )
    async def test_status_codes_become_typed_errors(self, error, expected) -> None:
        interactions = _FakeInteractions(error=error("provider said no"))
        with pytest.raises(expected):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_a_quota_message_without_a_status_is_a_rate_limit(self) -> None:
        interactions = _FakeInteractions(error=RuntimeError("quota exceeded for this project"))
        with pytest.raises(ProviderRateLimited):
            await _provider(interactions).complete(_PROMPT)

    async def test_a_safety_refusal_is_content_blocked(self) -> None:
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 400})("blocked by safety policy")
        )
        with pytest.raises(ContentBlocked):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_an_unrecognised_error_is_still_typed(self) -> None:
        interactions = _FakeInteractions(error=RuntimeError("something odd"))
        with pytest.raises(ProviderUnavailable):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_no_vendor_exception_escapes(self) -> None:
        """The contract the rest of the app relies on: five cases, not forty."""
        interactions = _FakeInteractions(error=KeyError("internal sdk detail"))
        with pytest.raises(ProviderError):
            await _provider(interactions).structured(_PROMPT, Direction)

    async def test_an_unconfigured_provider_says_so_without_calling_out(self) -> None:
        provider = GeminiLLMProvider(_settings(gemini_api_key=None))
        with pytest.raises(ProviderUnavailable):
            await provider.complete(_PROMPT)
        assert await provider.health() is False

    async def test_health_is_configuration_not_a_live_call(self) -> None:
        interactions = _FakeInteractions(_valid())
        assert await _provider(interactions).health() is True
        assert interactions.calls == []


class TestSecretsNeverReachTheLogs:
    """Section 8: the key stays server-side, out of every message and detail."""

    async def test_the_key_never_appears_in_a_user_facing_message(self) -> None:
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 401})("invalid api key test-key")
        )
        with pytest.raises(ProviderUnavailable) as caught:
            await _provider(interactions).structured(_PROMPT, Direction)
        assert "test-key" not in caught.value.message

    async def test_a_key_shaped_string_is_redacted_from_the_detail(self) -> None:
        """`detail` is log-side only, which is not a reason for a credential
        to be in it. Redaction is by shape, in `ProviderError.__init__`."""
        leaked = "AIzaSyDUMMYKEYFORTESTINGONLY0123456789"
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 400})(f"request failed: key={leaked}")
        )
        with pytest.raises(ProviderInvalidResponse) as caught:
            await _provider(interactions).complete(_PROMPT)
        assert leaked not in str(caught.value.detail)
        assert "[redacted]" in str(caught.value.detail)

    async def test_the_key_is_never_sent_in_the_request_body(self) -> None:
        """Authentication is the client's job. A key in the body would end up
        in every request log the provider keeps."""
        interactions = _FakeInteractions(_valid())
        await _provider(interactions).structured(_PROMPT, Direction)
        assert "test-key" not in json.dumps(interactions.calls[0], default=str)
