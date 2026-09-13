"""One controlled live image generation through the real Gemini adapter.

    uv run python scripts/gemini_smoke_test.py

**This is the only thing in the repository that reaches an external service.**
Nothing in the test suite does, the seed refuses to, and demo mode cannot. It
exists because "the adapter compiles" and "the adapter works" are different
claims, and the second one can only be made by making the call.

It proves the whole path in one go: settings → provider registry → the Gemini
adapter → a real image back → the `StorageProvider` → a readable object. A
failure at any step is reported as that step, because "Gemini is broken" and
"our storage key is wrong" need very different fixes.

Exit codes: `0` verified, `1` a credential problem (reported, not a crash),
`2` something else failed. It never prints the key, and it writes nothing to
the database — this is a provider check, not a campaign.
"""

from __future__ import annotations

import asyncio
import io
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, UnidentifiedImageError  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.providers.base import ImageRequest  # noqa: E402
from app.providers.registry import build_image_provider, build_storage_provider  # noqa: E402

#: Deliberately dull and non-branded. A smoke test should not spend a token on
#: anything it would be embarrassing to have generated, and should not look
#: like a campaign asset when it turns up in storage.
PROMPT = (
    "A plain studio photograph of a single grey anodised aluminium panel on a "
    "neutral background, even lighting, no text, no logos, no people."
)


def say(step: str, message: str) -> None:
    print(f"  {step:<12} {message}", flush=True)


async def main() -> int:
    settings = get_settings()

    if not settings.gemini_api_key:
        print("SKIPPED — no GEMINI_API_KEY is configured.")
        print("Live Gemini generation not verified because no credential was available.")
        return 1

    say(
        "config", f"model {settings.gemini_image_model}, key ending …{settings.gemini_api_key[-4:]}"
    )

    try:
        provider = build_image_provider(settings, "gemini")
    except Exception as exc:  # noqa: BLE001 - the point is to report, not raise
        print(f"FAILED — the Gemini provider could not be constructed: {exc}")
        return 2

    say("gemini", "requesting one image…")
    try:
        images = await provider.generate(
            ImageRequest(prompt=PROMPT, aspect_ratio="1:1", count=1, negative_prompt=None)
        )
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        print(f"FAILED — Gemini refused the request: {detail[:400]}")
        lowered = detail.lower()
        # Wide on purpose: the adapter maps provider errors to our own
        # sentences, so the wording here is ours and can change. Reading a
        # rejected key as "the provider call failed" would send someone
        # debugging the wrong thing.
        credential = any(
            word in lowered
            for word in (
                "credential",
                "api key",
                "api_key",
                "unauthenticated",
                "unauthorized",
                "permission",
                "invalid",
                "rejected",
                "401",
                "403",
            )
        )
        print(
            "Live Gemini generation not verified because the credential was rejected."
            if credential
            else "Live Gemini generation not verified: the provider call failed."
        )
        return 1 if credential else 2

    if not images:
        print("FAILED — Gemini returned no image.")
        return 2

    image = images[0]
    say("gemini", f"{len(image.data)} bytes, {image.width}x{image.height}, {image.mime_type}")

    try:
        with Image.open(io.BytesIO(image.data)) as decoded:
            decoded.load()
            say("decode", f"{decoded.format} {decoded.size[0]}x{decoded.size[1]}")
    except (UnidentifiedImageError, OSError) as exc:
        print(f"FAILED — the bytes Gemini returned are not a readable image: {exc}")
        return 2

    storage = build_storage_provider(settings)
    key = f"smoke-tests/gemini-{uuid.uuid4().hex}.png"
    await storage.put(key, image.data, mime_type=image.mime_type)
    stored = await storage.get(key)
    if stored != image.data:
        print("FAILED — what came back out of storage is not what went in.")
        return 2
    say("storage", f"round-tripped {len(stored)} bytes at {key}")

    print("\nPASSED — application → Gemini adapter → image → storage verified.")
    print(f"The object is at {key}; delete it when you are done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
