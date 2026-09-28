"""One controlled live structured call through the real Gemini LLM adapter.

    uv run python scripts/gemini_llm_smoke_test.py

**This, and the two other `gemini_*_smoke_test.py` scripts, are the only
things in the repository that reach an external service.** Nothing in the test
suite does, the seed refuses to, and demo mode cannot. They exist because "the
adapter compiles" and "the adapter works" are different claims, and the second
one can only be made by making the call.

It proves the whole path in one request: settings → provider registry → the
Gemini adapter → schema-constrained output → a validated `ProposedQuestion`.
`ProposedQuestion` is not a toy: it is the schema the campaign interview asks
for first, it is a `DomainModel` (so unknown fields are rejected), and it
carries a constrained string and an enum — the shapes a model actually gets
wrong.

Exit codes: `0` verified, `1` a credential problem (reported, not a crash),
`2` something else failed. It never prints the key, and it writes nothing to
the database — this is a provider check, not a campaign.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.providers.registry import build_llm_provider  # noqa: E402
from app.services.campaign_interviewer import ProposedQuestion  # noqa: E402

#: Deliberately dull and self-contained. A smoke test should not spend a token
#: on anything it would be embarrassing to have generated.
PROMPT = (
    "A manufacturer of aluminium facade systems wants to run a campaign and "
    "has told us nothing except that. Ask the single most useful next "
    "question. The field you are asking about is 'primary_audience'."
)

#: Words that mean "the key is the problem", matched wide on purpose: the
#: adapter maps provider errors to our own sentences, so the wording here is
#: ours and can change. Reading a rejected key as "the call failed" would send
#: someone debugging the wrong thing.
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
        print("Live Gemini reasoning not verified because no credential was available.")
        return 1

    # A masked suffix, so two people comparing notes can tell whether they are
    # using the same key. Never the key.
    say("config", f"model {settings.gemini_llm_model}, key ending …{settings.gemini_api_key[-4:]}")

    try:
        provider = build_llm_provider(settings)
    except Exception as exc:  # noqa: BLE001 — the point is to report, not raise
        print(f"FAILED — the Gemini LLM provider could not be constructed: {exc}")
        return 2
    if provider.name != "gemini":
        print(f"SKIPPED — LLM_PROVIDER is {provider.name!r}, not 'gemini'. Nothing was called.")
        return 1

    say("gemini", "requesting one structured ProposedQuestion…")
    try:
        question = await provider.structured(PROMPT, ProposedQuestion, temperature=0.4)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        print(f"FAILED — Gemini refused the request: {detail[:400]}")
        credential = any(word in detail.lower() for word in CREDENTIAL_WORDS)
        print(
            "Live Gemini reasoning not verified because the credential was rejected."
            if credential
            else "Live Gemini reasoning not verified: the provider call failed."
        )
        return 1 if credential else 2

    if not isinstance(question, ProposedQuestion):
        print(f"FAILED — got {type(question).__name__}, not a validated ProposedQuestion.")
        return 2

    say("schema", f"validated {type(question).__name__}, priority {question.priority}")
    say("content", f"field {question.field!r}")
    say("content", f"asked  {question.question[:120]!r}")

    print("\nPASSED — application → Gemini LLM adapter → schema-validated object verified.")
    print("Nothing was written to the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
