"""The one test that spends money.

**This never runs by default.** It is marked `live`, and `pyproject.toml` sets
`addopts = "-m 'not live'"`, so `uv run pytest` excludes it and CI can never
come to depend on an external API being up or a card being valid. Running it is
a deliberate act:

    GEMINI_API_KEY=… IMAGE_PROVIDER=gemini uv run pytest -m live

It also skips itself when no credential is configured, so a developer who opts
in on a machine without a key gets a skip rather than a failure.

**It generates exactly one image**, because every call is billable and a test
suite that quietly produced a dozen would be a way to lose money by running the
tests twice. `MAX_SMOKE_TEST_IMAGES` is one and is asserted, not assumed.

What it proves that no fake client can: that the configured model exists, that
the account may call it, that the bytes coming back decode, and that a real
plate flows into the deterministic renderer and out the other side as a
composed asset. Everything else about this adapter is covered offline in
`tests/test_image_providers.py`.
"""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from app.config import AppEnv, Settings
from app.providers.base import ImageRequest, ProviderError
from app.providers.gemini.image import SUPPORTED_MIME_TYPES, GeminiImageProvider
from app.services.renderer import RenderInputs, render

#: One. Not "a small number" — a literal, asserted below, so a future edit that
#: loops has to delete an assertion rather than change a default.
MAX_SMOKE_TEST_IMAGES = 1

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"),
        reason="no GEMINI_API_KEY configured — live generation is not verified",
    ),
]

PROMPT = (
    "Premium commercial advertising photograph of a modern consumer product on "
    "a sophisticated editorial set, cinematic lighting, realistic materials, "
    "natural shadows, subtle depth of field, luxury advertising aesthetic, "
    "clean negative space for later typography, no text, no logos."
)


def _settings() -> Settings:
    """Real providers, explicitly.

    `tests/conftest.py` pins `APP_ENV=test` and mock providers for the whole
    session, and `Settings` refuses a live provider under it. Opting out here
    is the point of this file, and doing it in one visible place is what keeps
    it from leaking into any other test.
    """
    return Settings(
        app_env=AppEnv.DEVELOPMENT,
        database_url="postgresql+asyncpg://localhost/unused",
        image_provider="gemini",
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        # Retries stay at the configured default (1). This test must not be
        # the thing that discovers an expensive retry loop.
        image_max_retries=int(os.environ.get("IMAGE_MAX_RETRIES", "1")),
    )


@pytest.fixture(scope="module")
def generated():
    """One image, generated once, shared by every assertion in this file.

    Module-scoped on purpose: per-test generation would multiply the bill by
    the number of assertions, and every assertion below is about the same
    image anyway.
    """
    import asyncio

    settings = _settings()
    provider = GeminiImageProvider(settings)
    try:
        images = asyncio.run(
            provider.generate(
                ImageRequest(
                    prompt=PROMPT,
                    aspect_ratio="1:1",
                    count=MAX_SMOKE_TEST_IMAGES,
                    parameters={"image_size": "1K"},
                )
            )
        )
    except ProviderError as exc:
        # The failure the user needs is the typed message plus the vendor's
        # own words. Neither can contain a credential — redaction happens in
        # `ProviderError.__init__` — so this is safe to put in a test report.
        pytest.fail(
            f"Live Gemini generation failed [{exc.code}]: {exc.message}\n"
            f"Provider detail: {exc.detail}"
        )
    assert images, "the adapter must never return an empty list silently"
    return images


class TestOneRealGeneration:
    def test_exactly_one_image_was_generated(self, generated) -> None:
        """Billing safety, asserted rather than trusted."""
        assert len(generated) == MAX_SMOKE_TEST_IMAGES == 1

    def test_the_response_contains_image_bytes(self, generated) -> None:
        assert isinstance(generated[0].data, bytes)
        assert len(generated[0].data) > 1024, "a plausible photograph, not a stub"

    def test_the_mime_type_is_one_we_support(self, generated) -> None:
        assert generated[0].mime_type in SUPPORTED_MIME_TYPES

    def test_the_bytes_decode_and_match_the_declared_type(self, generated) -> None:
        image = generated[0]
        with Image.open(io.BytesIO(image.data)) as decoded:
            decoded.load()
            assert decoded.format in ("PNG", "JPEG", "WEBP")
            # The recorded type must describe the actual bytes.
            assert decoded.format.lower() in image.mime_type

    def test_the_dimensions_are_real_and_recorded_correctly(self, generated) -> None:
        image = generated[0]
        assert image.width > 0 and image.height > 0
        with Image.open(io.BytesIO(image.data)) as decoded:
            assert (decoded.width, decoded.height) == (image.width, image.height)

    def test_provenance_records_what_produced_it(self, generated) -> None:
        meta = generated[0].metadata or {}
        assert meta["provider"] == "gemini"
        assert meta["model"]
        assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] > 0
        assert meta["returned_mime_type"] == generated[0].mime_type

    def test_no_credential_appears_in_the_provenance(self, generated) -> None:
        rendered = str(generated[0].metadata)
        assert os.environ["GEMINI_API_KEY"] not in rendered

    def test_the_plate_flows_into_the_deterministic_renderer(self, generated) -> None:
        """The thing the whole pipeline rests on: a real plate composes.

        The renderer is format-agnostic and outputs PNG regardless of what the
        model returned (ADR-014), so this is the end-to-end proof that a live
        plate becomes a branded asset.
        """
        from tests.test_composition import _layout, _logo

        composed = render(_layout(), RenderInputs(plate=generated[0].data, logo=_logo()))

        assert composed.mime_type == "image/png"
        with Image.open(io.BytesIO(composed.data)) as image:
            assert image.format == "PNG"
            assert image.size == (composed.width, composed.height)
