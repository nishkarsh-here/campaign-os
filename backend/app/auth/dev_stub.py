"""Development authentication.

Resolves every request to one configured identity. This exists so the
application runs locally, and demos, with no identity provider — a stated
requirement (DEMO SAFETY / ADR-002).

It is *not* a security control and must never be selected in production; the
guard below makes that a startup failure rather than a silent hole.
"""

from __future__ import annotations

from app.auth.base import AuthenticatedUser
from app.config import AppEnv, Settings


class DevStubAuthProvider:
    """Accepts anything and returns the configured demo identity."""

    name = "dev_stub"

    def __init__(self, settings: Settings) -> None:
        if settings.app_env is AppEnv.PRODUCTION:
            raise RuntimeError(
                "AUTH_PROVIDER=dev_stub authenticates every caller as the same user "
                "and must never run in production. Set AUTH_PROVIDER=supabase."
            )
        self._user = AuthenticatedUser(
            subject=f"dev-stub:{settings.dev_stub_user_email}",
            email=settings.dev_stub_user_email,
            display_name="Demo User",
        )

    async def authenticate(self, credentials: str | None) -> AuthenticatedUser:
        # The credential is ignored on purpose: there is nothing to verify.
        return self._user
