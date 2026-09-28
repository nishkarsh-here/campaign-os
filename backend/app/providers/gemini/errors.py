"""Vendor exception -> typed provider error, once for every Gemini adapter.

Gemini's error tree reaches this module and stops. All three adapters in this
package map the same way — a 429 is a rate limit whether it came from an image,
a completion or an embedding — and the only thing that differs is the noun in
the sentence a user reads. Three near-identical translators is how two of them
come to disagree about what a 403 means.

The vendor's own words go to `detail`, which is log-side only and is redacted
in `ProviderError.__init__`. What the user sees is a sentence that tells them
what happened, never a credential and never an instruction to go and find one.
"""

from __future__ import annotations

from app.providers.base import (
    ContentBlocked,
    ProviderError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderUnavailable,
)

#: Substrings that identify a safety refusal inside an otherwise ordinary
#: client error. A refusal is a product event — the UI offers a revision —
#: rather than a bug, so it must not be reported as a generic failure.
BLOCKED_MARKERS: tuple[str, ...] = ("safety", "blocked", "prohibited_content", "policy")


def status_of(exc: Exception) -> int | None:
    """The HTTP status behind a vendor exception, if it carries one."""
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def translate(exc: Exception, *, provider: str, subject: str) -> ProviderError:
    """Map one vendor exception onto our five cases.

    `subject` is the noun phrase the user sees — "The image service", "The
    model service" — so each adapter's messages read naturally while the
    classification stays identical across all of them.
    """
    status = status_of(exc)
    text = str(exc).lower()
    detail = f"{type(exc).__name__}: {exc}"[:500]

    if status == 429 or "rate limit" in text or "quota" in text:
        return ProviderRateLimited(
            f"{subject} is rate limited. Try again shortly.",
            detail=detail,
            provider=provider,
            retryable=True,
        )
    if any(marker in text for marker in BLOCKED_MARKERS):
        return ContentBlocked(
            f"{subject} refused this request on safety grounds.",
            detail=detail,
            provider=provider,
        )
    if status is not None and status >= 500:
        return ProviderUnavailable(
            f"{subject} is temporarily unavailable.",
            detail=detail,
            provider=provider,
            retryable=True,
        )
    if status in (401, 403):
        # Never echoes the key, and never tells a user to go and find it.
        # Deliberately NOT retryable: a rejected credential is rejected every
        # time, and a retry here is a second charge for the same answer.
        return ProviderUnavailable(
            f"{subject} rejected this workspace's credentials.", detail=detail, provider=provider
        )
    if status is not None and 400 <= status < 500:
        return ProviderInvalidResponse(
            f"{subject} could not process this request.", detail=detail, provider=provider
        )
    # Unrecognised, and usually a transport problem rather than a refusal.
    return ProviderUnavailable(
        f"{subject} could not be reached.", detail=detail, provider=provider, retryable=True
    )
