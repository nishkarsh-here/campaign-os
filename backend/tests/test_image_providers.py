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
    ImageRef,
    ImageRequest,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.providers.gemini.image import MAX_REFERENCE_IMAGES, GeminiImageProvider
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


def _jpeg(width: int = 64, height: int = 32) -> bytes:
    """What Gemini actually returns. JPEG is the only format it will produce."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _webp(width: int = 64, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode()


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


class _FlakyInteractions:
    """Fails `failures` times, then succeeds. The only way to prove a retry
    actually recovers rather than merely being attempted."""

    def __init__(self, *, failures: int, error: Exception, result) -> None:
        self._remaining = failures
        self._error = error
        self._result = result
        self.attempts = 0
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.attempts += 1
        self.calls.append(kwargs)
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        return self._result


class _FakeClient:
    def __init__(self, interactions) -> None:
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


def _provider(interactions, **settings_overrides) -> GeminiImageProvider:
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
            "mime_type": "image/jpeg",
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

    async def test_the_request_asks_for_jpeg(self) -> None:
        """Regression. The adapter used to hardcode `image/png`, which every
        Gemini image model refuses outright:

            400 invalid_request — "The value 'image/png' is not supported for
            'response_format.mime_type'. Supported values: 'image/jpeg'"

        It was invisible for as long as no working credential existed to make
        the call, which is exactly what the live smoke test is for.
        """
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_jpeg()).decode())))
        await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert interactions.calls[0]["response_format"]["mime_type"] == "image/jpeg"

    async def test_a_jpeg_payload_is_decoded_and_measured(self) -> None:
        jpeg = _jpeg(200, 100)
        interactions = _FakeInteractions(
            _Interaction(_Image(base64.b64encode(jpeg).decode(), mime_type="image/jpeg"))
        )
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))

        assert images[0].data == jpeg
        assert images[0].mime_type == "image/jpeg"
        assert (images[0].width, images[0].height) == (200, 100)

    async def test_the_fallback_mime_is_the_one_we_asked_for(self) -> None:
        """When the provider omits the type, assume what we requested — never
        a format it cannot return, which is how the row ends up lying."""
        interactions = _FakeInteractions(
            _Interaction(_Image(base64.b64encode(_jpeg()).decode(), mime_type=None))
        )
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert images[0].mime_type == "image/jpeg"

    async def test_metadata_is_safe(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(base64.b64encode(_png()).decode())))
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        rendered = str(images[0].metadata)
        assert "test-key" not in rendered
        assert set(images[0].metadata) == {
            "provider",
            "model",
            "status",
            "resolution",
            "request_id",
            "latency_ms",
            "requested_aspect_ratio",
            "requested_image_size",
            "requested_mime_type",
            "returned_mime_type",
            "reference_images",
        }


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


class TestReturnedFormatIsDetectedNotAssumed:
    """The request asks for JPEG, but what is recorded is what arrived. A row
    claiming PNG over JPEG bytes misleads everything that trusts it."""

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (_png(), "image/png"),
            (_jpeg(), "image/jpeg"),
            (_webp(), "image/webp"),
        ],
    )
    async def test_each_supported_format_is_recognised(self, payload, expected) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(payload))))
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert images[0].mime_type == expected
        assert images[0].width == 64 and images[0].height == 32

    async def test_the_bytes_win_over_a_wrong_declared_type(self) -> None:
        interactions = _FakeInteractions(
            _Interaction(_Image(_encoded(_png()), mime_type="image/jpeg"))
        )
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert images[0].mime_type == "image/png", "magic bytes are the authority"

    async def test_an_unreadable_format_is_refused(self) -> None:
        interactions = _FakeInteractions(
            _Interaction(_Image(_encoded(b"GIF89a-not-supported"), mime_type="image/gif"))
        )
        with pytest.raises(ProviderInvalidResponse):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))


class TestProvenance:
    async def test_it_records_what_produced_the_plate(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        images = await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, aspect_ratio="4:5", parameters={"image_size": "1K"})
        )

        meta = images[0].metadata or {}
        assert meta["provider"] == "gemini"
        assert meta["model"] == "m"
        assert meta["request_id"] == "int-1"
        assert meta["requested_aspect_ratio"] == "4:5"
        assert meta["requested_image_size"] == "1K"
        assert meta["requested_mime_type"] == "image/jpeg"
        assert meta["returned_mime_type"] == "image/jpeg"
        assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 0

    async def test_the_request_id_is_carried_as_the_provider_job_id(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg())), id="req-77"))
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert images[0].provider_job_id == "req-77"

    async def test_latency_reflects_a_slow_call(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))), delay=0.05)
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert (images[0].metadata or {})["latency_ms"] >= 40


class TestReferenceImages:
    async def test_references_are_sent_as_content_blocks(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        await _provider(interactions).generate(
            ImageRequest(
                prompt=_PROMPT,
                reference_images=(ImageRef(data=b"ref-bytes", mime_type="image/png"),),
            )
        )

        blocks = interactions.calls[0]["input"]
        assert [block["type"] for block in blocks] == ["image", "text"]
        assert base64.b64decode(blocks[0]["data"]) == b"ref-bytes"
        assert blocks[1]["text"] == _PROMPT

    async def test_without_references_the_input_stays_a_plain_string(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert interactions.calls[0]["input"] == _PROMPT

    async def test_a_reference_with_no_bytes_is_skipped_not_fatal(self) -> None:
        """A reference is guidance. Losing one must not fail a generation the
        way a missing subject would."""
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        images = await _provider(interactions).generate(
            ImageRequest(prompt=_PROMPT, reference_images=(ImageRef(storage_key="brand/ref.png"),))
        )
        assert images[0].data
        assert interactions.calls[0]["input"] == _PROMPT

    async def test_more_references_than_the_model_takes_are_trimmed(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        refs = tuple(ImageRef(data=f"ref{n}".encode()) for n in range(20))
        await _provider(interactions).generate(ImageRequest(prompt=_PROMPT, reference_images=refs))

        blocks = interactions.calls[0]["input"]
        assert sum(1 for b in blocks if b["type"] == "image") == MAX_REFERENCE_IMAGES


class TestRetriesAreBillableSoTheyAreNarrow:
    async def test_a_retryable_failure_is_tried_once_more_by_default(self) -> None:
        interactions = _FakeInteractions(
            _Interaction(_Image(_encoded(_jpeg()))),
            error=type("E503", (Exception,), {"code": 503})("upstream down"),
        )
        # Fails every attempt, so the count is what the setting allows.
        with pytest.raises(ProviderUnavailable):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert len(interactions.calls) == 2, "one call plus one retry"

    async def test_retries_can_be_switched_off(self) -> None:
        interactions = _FakeInteractions(
            error=type("E429", (Exception,), {"code": 429})("slow down")
        )
        with pytest.raises(ProviderRateLimited):
            await _provider(interactions, image_max_retries=0).generate(
                ImageRequest(prompt=_PROMPT)
            )
        assert len(interactions.calls) == 1

    async def test_the_retry_limit_is_honoured(self) -> None:
        interactions = _FakeInteractions(
            error=type("E503", (Exception,), {"code": 503})("still down")
        )
        with pytest.raises(ProviderUnavailable):
            await _provider(interactions, image_max_retries=3).generate(
                ImageRequest(prompt=_PROMPT)
            )
        assert len(interactions.calls) == 4

    async def test_the_limit_is_capped_so_spend_cannot_run_away(self) -> None:
        with pytest.raises(ValueError):
            _settings(image_max_retries=25)

    @pytest.mark.parametrize(
        "error",
        [
            type("E400", (Exception,), {"code": 400}),
            type("E401", (Exception,), {"code": 401}),
        ],
    )
    async def test_a_non_retryable_failure_is_never_repeated(self, error) -> None:
        """Retrying a refusal or a bad request spends money to be told the
        same thing twice."""
        interactions = _FakeInteractions(error=error("no"))
        with pytest.raises(ProviderError):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert len(interactions.calls) == 1

    async def test_a_safety_refusal_is_never_repeated(self) -> None:
        interactions = _FakeInteractions(
            error=type("E", (Exception,), {"code": 400})("blocked by safety policy")
        )
        with pytest.raises(ContentBlocked):
            await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert len(interactions.calls) == 1

    async def test_a_retry_that_succeeds_returns_the_image(self) -> None:
        """The point of retrying at all: a transient failure should not cost
        the user their generation."""
        interactions = _FlakyInteractions(
            failures=1,
            error=type("E503", (Exception,), {"code": 503})("blip"),
            result=_Interaction(_Image(_encoded(_jpeg()))),
        )
        images = await _provider(interactions).generate(ImageRequest(prompt=_PROMPT))
        assert images[0].data
        assert interactions.attempts == 2


class TestConfiguration:
    async def test_the_model_is_configuration_not_a_literal(self) -> None:
        interactions = _FakeInteractions(_Interaction(_Image(_encoded(_jpeg()))))
        await _provider(interactions, gemini_image_model="gemini-3-pro-image").generate(
            ImageRequest(prompt=_PROMPT)
        )
        assert interactions.calls[0]["model"] == "gemini-3-pro-image"

    def test_the_default_model_is_the_current_one(self) -> None:
        assert _settings().gemini_image_model == "gemini-3.1-flash-image"

    async def test_a_missing_key_fails_before_any_call(self) -> None:
        provider = GeminiImageProvider(_settings(gemini_api_key=None))
        with pytest.raises(ProviderUnavailable):
            await provider.generate(ImageRequest(prompt=_PROMPT))

    def test_selecting_gemini_without_a_key_is_refused_at_startup(self) -> None:
        with pytest.raises(ValueError):
            _settings(image_provider="gemini", gemini_api_key=None)

    def test_a_blank_model_is_refused_at_startup(self) -> None:
        with pytest.raises(ValueError):
            _settings(image_provider="gemini", gemini_image_model="  ")
