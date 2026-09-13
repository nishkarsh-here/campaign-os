"""Configuration -> concrete auth provider.

The same lazy-import pattern as `app/providers/registry.py`: selecting the dev
stub never imports a cloud SDK.
"""

from __future__ import annotations

from functools import lru_cache

from app.auth.base import AuthProvider
from app.config import Settings, get_settings


def build_auth_provider(settings: Settings | None = None) -> AuthProvider:
    s = settings or get_settings()
    match s.auth_provider:
        case "dev_stub":
            from app.auth.dev_stub import DevStubAuthProvider

            return DevStubAuthProvider(s)
        case "supabase":  # pragma: no cover - Milestone 10
            from app.auth.supabase import SupabaseAuthProvider

            return SupabaseAuthProvider(s)
        case other:
            raise RuntimeError(f"Unknown AUTH_PROVIDER {other!r}. Available: dev_stub, supabase")


@lru_cache
def get_auth_provider() -> AuthProvider:
    return build_auth_provider()
