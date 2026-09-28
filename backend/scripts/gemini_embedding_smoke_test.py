"""One controlled live embedding call through the real Gemini adapter.

    uv run python scripts/gemini_embedding_smoke_test.py

One of the three scripts in this repository that reach an external service.
See `gemini_llm_smoke_test.py` for why they exist.

It proves the one thing that cannot be proved offline: that the configured
model, asked for the configured width, actually returns vectors of that width
— which is what `brand_chunks.embedding` is declared at. It asks for two
texts, because "one embedding came back" and "one embedding per text came
back" are different claims.

**It prints dimensionality, counts and norms. It never prints a vector**, and
never the key. An embedding is derived from its input, and a smoke test is not
the place to start emitting content into a terminal or a CI log.

Exit codes: `0` verified, `1` a credential problem (reported, not a crash),
`2` something else failed. It writes nothing to the database.
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.models import EMBEDDING_DIMENSIONS  # noqa: E402
from app.providers.registry import build_embedding_provider  # noqa: E402

#: Two short, unrelated, entirely unremarkable strings.
TEXTS = [
    "Aluminium facade systems for commercial buildings.",
    "A recipe for a plain vegetable soup.",
]

CREDENTIAL_WORDS = (
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


def say(step: str, message: str) -> None:
    print(f"  {step:<12} {message}", flush=True)


async def main() -> int:
    settings = get_settings()

    if not settings.gemini_api_key:
        print("SKIPPED — no GEMINI_API_KEY is configured.")
        print("Live Gemini embeddings not verified because no credential was available.")
        return 1

    say(
        "config",
        f"model {settings.gemini_embedding_model}, "
        f"asking for {settings.gemini_embedding_dimensions} dimensions, "
        f"key ending …{settings.gemini_api_key[-4:]}",
    )

    try:
        provider = build_embedding_provider(settings)
    except Exception as exc:  # noqa: BLE001 — the point is to report, not raise
        print(f"FAILED — the Gemini embedding provider could not be constructed: {exc}")
        return 2
    if provider.name != "gemini":
        print(
            f"SKIPPED — EMBEDDING_PROVIDER is {provider.name!r}, not 'gemini'. Nothing was called."
        )
        return 1

    say("gemini", f"embedding {len(TEXTS)} short texts…")
    try:
        vectors = await provider.embed(TEXTS)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        print(f"FAILED — Gemini refused the request: {detail[:400]}")
        credential = any(word in detail.lower() for word in CREDENTIAL_WORDS)
        print(
            "Live Gemini embeddings not verified because the credential was rejected."
            if credential
            else "Live Gemini embeddings not verified: the provider call failed."
        )
        return 1 if credential else 2

    if len(vectors) != len(TEXTS):
        print(f"FAILED — asked for {len(TEXTS)} vectors, received {len(vectors)}.")
        return 2

    widths = {len(vector) for vector in vectors}
    say("shape", f"{len(vectors)} vectors, width {sorted(widths)}")
    if widths != {EMBEDDING_DIMENSIONS}:
        print(
            f"FAILED — brand_chunks.embedding is vector({EMBEDDING_DIMENSIONS}); "
            f"got width {sorted(widths)}. Nothing was truncated — fix the "
            "configuration, or migrate the column and re-embed."
        )
        return 2

    norms = [math.sqrt(sum(value * value for value in vector)) for vector in vectors]
    say("norm", ", ".join(f"{norm:.6f}" for norm in norms))
    if not all(math.isclose(norm, 1.0, rel_tol=1e-6) for norm in norms):
        print("FAILED — vectors are not unit length; cosine distance would be wrong.")
        return 2

    print(
        f"\nPASSED — application → Gemini embedding adapter → "
        f"{len(vectors)} normalised vector(s) of {EMBEDDING_DIMENSIONS} dimensions verified."
    )
    print("No vector was printed and nothing was written to the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
