"""Image providers: the mock, and the Gemini adapter driven by a fake SDK.

No test here reaches the network. The Gemini cases construct the adapter with
an injected client, so every branch of the outcome-to-typed-error mapping is
verified without a credit being spent — which is the whole point of the
abstraction being a Protocol rather than a base class.
"""

from __future__ import annotations

import asyncio
import base64
import io

import pytest
from PIL import Image

from app.config import Settings
from app.providers.base import (
    ContentBlocked,
    ImageRequest,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.image import GeminiImageProvider
from app.providers.mock.image import MockImageProvider

pytestmark = pytest.mark.unit

_PROMPT = "Subject: a single bay of a facade\nPalette: #1F2933, #E4572E"


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "gemini_api_key": "test-key",
        "generation_timeout_s": 5,
    }
    return Settings(**{**base, **overrides})


def _png(width: int = 64, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------- the mock
class TestMockProvider:
    async def test_it_returns_a_real_image(self) -> None:
        images = await MockImageProvider().generate(ImageRequest(prompt=_PROMPT))
        assert len(images) == 1
        assert images[0].mime_type == "image/png"
        with Image.open(io.BytesIO(images[0].data)) as opened:
            assert (opened.width, opened.height) == (images[0].width, images[0].height)

    async def test_the_same_prompt_gives_the_same_image(self) -> None:
        """Determinism is what makes the offline demo and the tests reliable."""
        provider = MockImageProvider()
        first = await provider.generate(ImageRequest(prompt=_PROMPT))
        second = await provider.generate(ImageRequest(prompt=_PROMPT))
        assert first[0].data == second[0].data

    async def test_a_different_prompt_gives_a_different_image(self) -> None:
        provider = MockImageProvider()
        first = await provider.generate(ImageRequest(prompt=_PROMPT))
        second = await provider.generate(ImageRequest(prompt="Subject: a person"))
        assert first[0].data != second[0].data

    async def test_the_aspect_ratio_decides_the_frame(self) -> None:
        provider = MockImageProvider()
        tall = await provider.generate(ImageRequest(prompt=_PROMPT, aspect_ratio="9:16"))
        wide = await provider.generate(ImageRequest(prompt=_PROMPT, aspect_ratio="16:9"))
        assert tall[0].height > tall[0].width
        assert wide[0].width > wide[0].height

    async def test_count_is_respected_and_images_differ(self) -> None:
        images = await MockImageProvider().generate(ImageRequest(prompt=_PROMPT, count=3))
        assert len(images) == 3
        assert len({image.data for image in images}) == 3

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            ("timeout", ProviderTimeout),
            ("rate_limit", ProviderRateLimited),
            ("unavailable", ProviderUnavailable),
            ("blocked", ContentBlocked),
            ("malformed", ProviderInvalidResponse),
        ],
    )
    async def test_each_failure_mode_raises_its_typed_error(self, mode, expected) -> None:
        with pytest.raises(expected):
            await MockImageProvider(mode).generate(ImageRequest(prompt=_PROMPT))

    async def test_health_reports_a_broken_provider(self) -> None:
        assert await MockImageProvider().health() is True
        assert await MockImageProvider("unavailable").health() is False

    async def test_a_retry_after_a_failure_succeeds(self) -> None:
        """Recoverability: a failed job is retried against a working provider,
        which is exactly what the Retry button does."""
        with pytest.raises(ProviderTimeout):
            await MockImageProvider("timeout").generate(ImageRequest(prompt=_PROMPT))
        images = await MockImageProvider().generate(ImageRequest(prompt=_PROMPT))
        assert images[0].data


# ------------------------------------------------------- the Gemini adapter
class _FakeInteractions:
    """Stands in for `client.aio.interactions`."""

    def __init__(self, result=None, error: Exception | None = None, delay: float = 0.0) -> None:
        self._result = result
        self._error = error
        self._delay = delay
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeClient:
    def __init__(self, interactions: _FakeInteractions) -> None:
        self.aio = type("Aio", (), {"interactions": interactions})()


class _Image:
    def __init__(self, data, mime_type="image/png", resolution="2K") -> None:
        self.data = data
        self.mime_type = mime_type
        self.resolution = resolution


class _Interaction:
    def __init__(self, output_image=None, status="completed", id="int-1", model="m") -> None:
        self.output_image = output_image
        self.status = status
        self.id = id
        self.model = model


def _provider(interactions: _FakeInteractions, **settings_overrides) -> GeminiImageProvider:
    return GeminiImageProvider(_settings(**settings_overrides), client=_FakeClient(interactions))


class TestGeminiAdapterSuccess:
    async def test_it_decodes_the_returned_image(self) -> None:
        png = _png(128, 64)
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(png).decode())))
        images = await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, aspect_ratio="16:9")
        )

        assert len(images) == 1
        assert images[0].data == png
        assert (images[0].width, images[0].height) == (128, 64)

    async def test_dimensions_come_from_the_bytes_not_the_request(self) -> None:
        """The provider may return a frame one step from what was asked; a row
        claiming a size it does not have would mislead everything downstream."""
        interactions = _FakeInteractions(
            _Interaction(_Image(base64.b64encode(_png(100, 100)).decode()))
        )
        images = await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, aspect_ratio="9:16")
        )
        assert (images[0].width, images[0].height) == (100, 100)

    async def test_it_sends_only_documented_fields(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, aspect_ratio="16:9", parameters={"image_size": "2K"})
        )

        (call,) = interactions.calls
        assert set(call) == {"model", "input", "response_format"}
        assert call["response_format"] == {
            "type": "image",
            "mime_type": "image/png",
            "aspect_ratio": "16:9",
            "image_size": "2K",
        }

    async def test_an_undocumented_image_size_is_replaced(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, parameters={"image_size": "9000px"})
        )
        assert interactions.calls[0]["response_format"]["image_size"] == "2K"

    async def test_an_unsupported_ratio_falls_back_to_square(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        await _provider(interactions).generate(ImageRequest(prompt=_PROMPT, aspect_ratio="7:3"))
        assert interactions.calls[0]["response_format"]["aspect_ratio"] == "1:1"

    async def test_a_separate_negative_prompt_is_appended(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        await _provider(interactions).generate(
            ImageRequest(prompt="A facade", negative_prompt="any text")
        )
        assert "Do not include: any text." in interactions.calls[0]["input"]

    async def test_metadata_is_safe(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        rendered = str(images[0].metadata)
        assert "test-key" not in rendered
        assert set(images[0].metadata) == {"model", "status", "resolution"}


class TestGeminiAdapterFailures:
    async def test_a_missing_image_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction(output_image=None, status="failed"))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_an_empty_image_payload_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image("")))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_undecodable_base64_is_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image("not base64 !!!")))
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_bytes_that_are_not_an_image_are_an_invalid_response(self) -> None:
        interactions = _FakeInteractions(
            _Interaction(_Image(base64.b64encode(b"this is not a png").decode()))
        )
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_a_slow_provider_times_out(self) -> None:
        interactions = _FakeInteractions(
            _Interaction(_Image(base64.b64encode(_png()).decode())), delay=0.2
        )
        provider = GeminiImageProvider(
            _settings(generation_timeout_s=0), client=_FakeClient(interactions)
        )
        with pytest.raises(ProviderTimeout):
            await provider.generate(ImageRequest(prompt=_PROMPT))

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (_Err := type("E429", (Exception,), {"code": 429}), ProviderRateLimited),
            (type("E500", (Exception,), {"code": 503}), ProviderUnavailable),
            (type("E401", (Exception,), {"code": 401}), ProviderUnavailable),
            (type("E400", (Exception,), {"code": 400}), ProviderInvalidResponse),
        ],
    )
    async def test_status_codes_become_typed_errors(self, error, expected) -> None:
        interactions = _FakeInteractions(error=error("provider said no"))
        with pytest.raises(expected):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_a_safety_refusal_is_content_blocked(self) -> None:
        """A refusal is a product event the UI explains, not a bug."""
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 400})("blocked by safety policy")
        )
        with pytest.raises(ContentBlocked):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_an_unrecognised_error_is_still_typed(self) -> None:
        interactions = _FakeInteractions(error=RuntimeError("something odd"))
        with pytest.raises(ProviderUnavailable):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

    async def test_no_vendor_exception_escapes(self) -> None:
        """The contract the rest of the app relies on: five cases, not forty."""
        interactions = _FakeInteractions(error=KeyError("internal sdk detail"))
        with pytest.raises(Exception) as caught:
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert not isinstance(caught.value, KeyError)

    async def test_the_api_key_never_appears_in_a_user_facing_message(self) -> None:
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 401})("invalid api key test-key")
        )
        with pytest.raises(ProviderUnavailable) as caught:
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert "test-key" not in caught.value.message

    async def test_an_unconfigured_provider_says_so_without_calling_out(self) -> None:
        provider = GeminiImageProvider(_settings(gemini_api_key=None))
        with pytest.raises(ProviderUnavailable):
            await provider.generate(ImageRequest(prompt=_PROMPT))
        assert await provider.health() is False


class TestSecretsNeverReachTheLogs:
    """`ProviderError.detail` is log-side only — which is not a reason for a
    credential to be in it.

    Vendor exceptions quote the request that produced them, and a provider that
    authenticates by query parameter puts the key in that request. Redaction
    happens in `ProviderError.__init__` because that is the one place every
    adapter's vendor detail passes through.
    """

    @pytest.mark.parametrize(
        "detail",
        [
            "ClientError: 400 GET https://api.example.com/v1/models?key=AIzaSyD1234567890abcdefgh",
            'Unauthorized: {"api_key": "sk-live-abcdef1234567890"}',
            "authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
            "x-goog-api-key: AIzaSyD1234567890abcdefghijk",
        ],
    )
    def test_a_key_shaped_string_never_survives(self, detail: str) -> None:
        error = ProviderError("The service is unavailable.", detail=detail, provider="gemini")
        assert error.detail is not None
        assert "[redacted]" in error.detail
        for secret in (
            "AIzaSyD1234567890abcdefgh",
            "sk-live-abcdef1234567890",
            "eyJhbGciOiJIUzI1NiJ9",
        ):
            assert secret not in error.detail

    def test_an_ordinary_message_is_left_alone(self) -> None:
        """Over-redaction is its own failure: a detail of all asterisks tells
        whoever is debugging nothing at all."""
        detail = "ServerError: 503 after 2 retries, upstream timed out"
        error = ProviderError("Temporarily unavailable.", detail=detail, provider="gemini")
        assert error.detail == detail

    def test_the_user_facing_message_is_untouched(self) -> None:
        error = ProviderError("The image service is rate limited.", detail="key=AIzaSyDabcdefghij")
        assert error.message == "The image service is rate limited."
