"""Production authentication against Supabase Auth.

**How a credential is verified.** The bearer token is sent to Supabase's own
`GET /auth/v1/user` endpoint. A `200` means the session is valid; anything else
means it is not. This is the check Supabase documents for server-side
validation, and it is deliberately chosen over verifying the JWT locally with
the project's shared secret — which Supabase itself recommends against.

The trade-off is real and worth stating: a network call per request, to an Auth
server that lives in one region. It is accepted for two reasons. Local JWT
verification cannot see a session that has been signed out or revoked — it will
keep accepting the token until it expires — and this application's whole
posture is that authorization is checked at the boundary rather than inferred.
And hand-rolling JWS verification against a JWKS, with no JWT library in the
dependency set, is the kind of security code that should never be written when
the vendor publishes an endpoint that answers the same question.

The latency is bounded by a short TTL cache, so a burst of requests from one
session costs one round trip rather than twenty. The cache is keyed by a digest
of the token, never the token, so a heap dump or a debugger does not hand
someone a live session.

**This provider never touches the database.** It answers "who is this?" and
nothing else; provisioning the user and resolving the organization are
`app/api/deps.py`'s job, exactly as with the dev stub (ADR-002).

**Identity is the subject.** `users.auth_subject` binds to Supabase's `id`,
and there is deliberately no fallback to email: an email can be reassigned
between people, and treating it as identity is how one person inherits
another's memberships (M1_SECURITY_AUDIT §A-1).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from app.auth.base import AuthenticatedUser, AuthenticationError
from app.config import Settings
from app.logging import get_logger

log = get_logger(__name__)

#: How long a verified session is trusted without re-asking Supabase.
#:
#: Short on purpose. This is the window in which a signed-out session still
#: works, so it trades a little staleness for a lot of latency. Thirty seconds
#: collapses a page-load burst into one round trip while keeping revocation
#: effectively immediate from a person's point of view.
CACHE_TTL_SECONDS = 30.0

#: A ceiling so a long-running process cannot accumulate entries without
#: bound. Far above any realistic concurrent-session count for one instance.
CACHE_MAX_ENTRIES = 2048

#: Supabase's own validation endpoint.
USER_PATH = "/auth/v1/user"

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _digest(token: str) -> str:
    """A cache key that is not the credential.

    Tokens must not sit in a dictionary in memory any longer than the request
    that carried them, so the cache remembers a hash and never the original.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SupabaseAuthProvider:
    """Resolves a Supabase access token to an identity."""

    name = "supabase"

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            # A startup failure, not a per-request one: a misconfigured auth
            # provider must never become a 401 that looks like a bad password.
            raise RuntimeError(
                "AUTH_PROVIDER=supabase requires SUPABASE_URL and SUPABASE_ANON_KEY."
            )
        self._base_url = settings.supabase_url.rstrip("/")
        # The publishable (anon) key identifies the project. Deliberately not
        # the service-role key: this request already carries the user's own
        # token, so it needs no privilege of its own, and the service-role key
        # would be a standing escalation for no benefit.
        self._anon_key = settings.supabase_anon_key
        self._client = client
        self._cache: dict[str, tuple[float, AuthenticatedUser]] = {}

    async def authenticate(self, credentials: str | None) -> AuthenticatedUser:
        if not credentials or not credentials.strip():
            raise AuthenticationError("No credential was presented.")
        token = credentials.strip()

        key = _digest(token)
        cached = self._cache.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]

        identity = await self._verify(token)
        self._remember(key, identity)
        return identity

    async def _verify(self, token: str) -> AuthenticatedUser:
        client = self._client or httpx.AsyncClient(timeout=_TIMEOUT)
        owns_client = self._client is None
        try:
            response = await client.get(
                f"{self._base_url}{USER_PATH}",
                headers={
                    "apikey": self._anon_key,
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            # The identity provider being unreachable is not the caller's
            # fault, but there is no safe way to proceed: refusing is the only
            # correct answer. The exception type is logged, never the token.
            log.warning("supabase_auth_unreachable", error=type(exc).__name__)
            raise AuthenticationError("The identity provider could not be reached.") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code != 200:
            # Every non-200 collapses to one answer. Distinguishing "expired"
            # from "malformed" here would tell an attacker which of their
            # guesses was closer, and the user's remedy is the same either way.
            log.info("supabase_auth_rejected", status=response.status_code)
            raise AuthenticationError("That session is not valid.")

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise AuthenticationError(
                "The identity provider returned an unreadable reply."
            ) from exc

        return _identity_from(payload)

    def _remember(self, key: str, identity: AuthenticatedUser) -> None:
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            # Cheapest possible eviction: drop everything rather than track
            # recency. The cache is a latency optimisation, and rebuilding it
            # costs one round trip per live session.
            self._cache.clear()
        self._cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, identity)


def _identity_from(payload: Any) -> AuthenticatedUser:
    """Supabase's user object -> our identity.

    Both `id` and `email` are required. An identity with no stable subject
    cannot be bound to a user row, and one with no email cannot be provisioned
    — so a reply missing either is treated as a failed authentication rather
    than as a user with blank fields.
    """
    if not isinstance(payload, dict):
        raise AuthenticationError("The identity provider returned an unexpected reply.")

    subject = payload.get("id")
    email = payload.get("email")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("The identity provider returned no subject.")
    if not isinstance(email, str) or not email:
        # Never falls back to another field. An account without an email is
        # one this application cannot provision, and inventing one would put a
        # placeholder into the users table for ever.
        raise AuthenticationError("That account has no email address.")

    return AuthenticatedUser(
        subject=subject,
        email=email,
        display_name=_display_name(payload),
    )


def _display_name(payload: dict[str, Any]) -> str | None:
    """A human name if the provider has one, otherwise nothing.

    Read from `user_metadata`, which is where Supabase puts whatever the
    sign-up flow or OAuth provider supplied. Absent is a perfectly good
    answer — `upsert_from_identity` fills it in later if it ever arrives.
    """
    metadata = payload.get("user_metadata")
    if not isinstance(metadata, dict):
        return None
    for field in ("full_name", "name", "display_name"):
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
