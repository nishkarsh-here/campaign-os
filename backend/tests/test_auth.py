"""The auth boundary.

What matters here is not that the stub works — it is that it stays a *stub*:
replaceable, and impossible to run in production by accident.
"""

from __future__ import annotations

import pytest

from app.auth.base import AuthenticatedUser, AuthProvider
from app.auth.dev_stub import DevStubAuthProvider
from app.auth.registry import build_auth_provider
from app.config import Settings
from tests.conftest import production_settings

pytestmark = pytest.mark.unit


def _settings(**overrides) -> Settings:
    return Settings(**{"app_env": "development", "auth_provider": "dev_stub", **overrides})


class TestDevStub:
    def test_it_satisfies_the_auth_protocol(self) -> None:
        assert isinstance(DevStubAuthProvider(_settings()), AuthProvider)

    async def test_it_returns_the_configured_identity(self) -> None:
        provider = DevStubAuthProvider(_settings(dev_stub_user_email="a@b.test"))
        identity = await provider.authenticate(None)
        assert isinstance(identity, AuthenticatedUser)
        assert identity.email == "a@b.test"
        assert identity.subject == "dev-stub:a@b.test"

    async def test_the_credential_is_ignored(self) -> None:
        """There is nothing to verify — which is exactly why it must never
        reach production."""
        provider = DevStubAuthProvider(_settings())
        assert await provider.authenticate("garbage") == await provider.authenticate(None)

    def test_it_refuses_to_construct_in_production(self) -> None:
        with pytest.raises(RuntimeError, match="never run in production"):
            # Production has several other guards — a signing key, real CORS,
            # a database that is not localhost. `production_settings` supplies
            # them, because this test is about the auth one.
            DevStubAuthProvider(production_settings(auth_provider="dev_stub"))


class TestRegistry:
    def test_it_builds_the_configured_provider(self) -> None:
        assert build_auth_provider(_settings()).name == "dev_stub"

    def test_an_unknown_provider_fails_loudly(self) -> None:
        with pytest.raises(RuntimeError, match="Unknown AUTH_PROVIDER"):
            build_auth_provider(_settings(auth_provider="magic"))


class TestSeparationOfConcerns:
    def test_the_provider_returns_an_identity_not_a_principal(self) -> None:
        """Identity and organization are resolved separately, so swapping the
        IdP cannot affect membership logic (app/auth/base.py)."""
        import inspect

        signature = inspect.signature(DevStubAuthProvider.authenticate)
        assert signature.return_annotation == "AuthenticatedUser"
        assert not hasattr(AuthenticatedUser, "organization_id")
