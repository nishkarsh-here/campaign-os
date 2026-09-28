"""The production auth provider, driven against a fake Supabase.

No network. `respx` intercepts httpx, so every branch of the verify path is
exercised without a project, a key or a round trip — the same discipline the
Gemini adapters follow with a fake SDK client.

What these hold, in order of how much damage getting it wrong would do:
identity is the subject and never the email; a token never reaches a log or a
cache key; every rejection collapses to one answer; and the dev stub is
untouched by any of it.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.auth.base import AuthenticatedUser, AuthenticationError, AuthProvider
from app.auth.dev_stub import DevStubAuthProvider
from app.auth.registry import build_auth_provider
from app.auth.supabase import (
    CACHE_TTL_SECONDS,
    USER_PATH,
    SupabaseAuthProvider,
    _digest,
)
from app.config import AppEnv, Settings

pytestmark = pytest.mark.unit

PROJECT = "https://project.supabase.co"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake-access-token.signature"
SUBJECT = "9f1b0e7c-0000-4000-8000-000000000001"

USER_PAYLOAD = {
    "id": SUBJECT,
    "email": "priya@example.test",
    "user_metadata": {"full_name": "Priya Nair"},
}


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+asyncpg://localhost/test",
        "auth_provider": "supabase",
        "supabase_url": PROJECT,
        "supabase_anon_key": "anon-publishable-key",
        # Production `Settings` refuses to build without one. Unrelated to
        # authentication, but these tests construct production settings.
        "media_url_secret": "test-signing-key",
    }
    return Settings(**{**base, **overrides})


def _provider(**overrides) -> SupabaseAuthProvider:
    return SupabaseAuthProvider(_settings(**overrides))


# ------------------------------------------------------------ valid identity
class TestAValidSession:
    @respx.mock
    async def test_it_resolves_to_an_identity(self) -> None:
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        identity = await _provider().authenticate(TOKEN)

        assert isinstance(identity, AuthenticatedUser)
        assert identity.subject == SUBJECT
        assert identity.email == "priya@example.test"
        assert identity.display_name == "Priya Nair"
        assert route.called

    @respx.mock
    async def test_it_sends_the_token_and_the_project_key(self) -> None:
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        await _provider().authenticate(TOKEN)

        request = route.calls[0].request
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["apikey"] == "anon-publishable-key"

    @respx.mock
    async def test_it_never_sends_the_service_role_key(self) -> None:
        """Auth carries the caller's own token, so it needs no privilege of
        its own. A service-role key here would be a standing escalation."""
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        await _provider(supabase_service_role_key="SERVICE-ROLE-SECRET").authenticate(TOKEN)

        rendered = str(dict(route.calls[0].request.headers))
        assert "SERVICE-ROLE-SECRET" not in rendered

    @respx.mock
    async def test_a_missing_display_name_is_not_invented(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json={"id": SUBJECT, "email": "a@b.test"})
        )
        assert (await _provider().authenticate(TOKEN)).display_name is None

    @respx.mock
    @pytest.mark.parametrize("field", ["full_name", "name", "display_name"])
    async def test_any_metadata_name_field_is_accepted(self, field) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(
                200,
                json={"id": SUBJECT, "email": "a@b.test", "user_metadata": {field: "Asha"}},
            )
        )
        assert (await _provider().authenticate(TOKEN)).display_name == "Asha"


# --------------------------------------------------------------- rejections
class TestAnInvalidSession:
    @pytest.mark.parametrize("credential", [None, "", "   "])
    async def test_a_missing_credential_is_refused_without_a_call(self, credential) -> None:
        """No round trip for a request that obviously carries nothing."""
        with respx.mock:
            route = respx.get(f"{PROJECT}{USER_PATH}")
            with pytest.raises(AuthenticationError):
                await _provider().authenticate(credential)
            assert not route.called

    @respx.mock
    @pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 503])
    async def test_every_rejection_gives_the_same_answer(self, status) -> None:
        """Distinguishing 'expired' from 'malformed' tells an attacker which
        guess was closer, and the user's remedy is identical either way."""
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(status))
        with pytest.raises(AuthenticationError, match="not valid"):
            await _provider().authenticate(TOKEN)

    @respx.mock
    async def test_an_unreachable_provider_refuses_rather_than_assumes(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(AuthenticationError, match="could not be reached"):
            await _provider().authenticate(TOKEN)

    @respx.mock
    async def test_an_unreadable_reply_is_refused(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, content=b"not json")
        )
        with pytest.raises(AuthenticationError):
            await _provider().authenticate(TOKEN)

    @respx.mock
    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "a@b.test"},
            {"id": "", "email": "a@b.test"},
            {"id": 12345, "email": "a@b.test"},
            ["not", "an", "object"],
        ],
    )
    async def test_a_reply_with_no_usable_subject_is_refused(self, payload) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(AuthenticationError):
            await _provider().authenticate(TOKEN)


# ------------------------------------------------------- identity discipline
class TestIdentityIsTheSubject:
    @respx.mock
    async def test_an_account_with_no_email_is_refused_not_substituted(self) -> None:
        """The rule that matters most (M1_SECURITY_AUDIT §A-1).

        There is no fallback from subject to email and none from email to
        anything else. A blank-email account must not be provisioned with an
        invented address, because that address would live in `users` for ever.
        """
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json={"id": SUBJECT, "email": ""})
        )
        with pytest.raises(AuthenticationError, match="no email"):
            await _provider().authenticate(TOKEN)

    @respx.mock
    async def test_the_subject_is_the_provider_id_not_the_email(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(200, json=USER_PAYLOAD))
        identity = await _provider().authenticate(TOKEN)
        assert identity.subject == SUBJECT
        assert identity.subject != identity.email

    @respx.mock
    async def test_two_accounts_sharing_an_email_keep_separate_subjects(self) -> None:
        """Supabase can be configured to allow it; identity must still split."""
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json={"id": "subject-a", "email": "same@b.test"})
        )
        first = await _provider().authenticate("token-a")
        respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json={"id": "subject-b", "email": "same@b.test"})
        )
        second = await _provider().authenticate("token-b")
        assert first.subject != second.subject


# ----------------------------------------------------------------- secrecy
class TestTheTokenIsNeverRetained:
    def test_the_cache_key_is_a_digest_not_the_token(self) -> None:
        key = _digest(TOKEN)
        assert TOKEN not in key
        assert len(key) == 64

    @respx.mock
    async def test_no_token_appears_in_the_cache(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(200, json=USER_PAYLOAD))
        provider = _provider()
        await provider.authenticate(TOKEN)

        rendered = str(provider._cache)
        assert TOKEN not in rendered

    @respx.mock
    async def test_no_token_reaches_the_logs(self, caplog) -> None:
        """`caplog` over the real logger: a rejected credential is the case
        where a token is most likely to be echoed for debugging."""
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(401))
        with pytest.raises(AuthenticationError):
            await _provider().authenticate(TOKEN)
        assert TOKEN not in caplog.text
        assert "Bearer" not in caplog.text

    @respx.mock
    async def test_the_error_message_does_not_echo_the_credential(self) -> None:
        respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(401))
        with pytest.raises(AuthenticationError) as caught:
            await _provider().authenticate(TOKEN)
        assert TOKEN not in str(caught.value)


# ------------------------------------------------------------------- cache
class TestTheVerificationCache:
    @respx.mock
    async def test_a_repeat_within_the_window_costs_one_round_trip(self) -> None:
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        provider = _provider()
        for _ in range(5):
            await provider.authenticate(TOKEN)
        assert route.call_count == 1

    @respx.mock
    async def test_a_different_token_is_verified_separately(self) -> None:
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        provider = _provider()
        await provider.authenticate("token-one")
        await provider.authenticate("token-two")
        assert route.call_count == 2

    @respx.mock
    async def test_an_expired_entry_is_re_verified(self, monkeypatch) -> None:
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(
            return_value=httpx.Response(200, json=USER_PAYLOAD)
        )
        # The fake clock has to be in place for the *first* call too, or the
        # entry is stamped against real uptime and no plausible fake value is
        # past it.
        clock = [1000.0]
        monkeypatch.setattr("app.auth.supabase.time.monotonic", lambda: clock[0])
        provider = _provider()
        await provider.authenticate(TOKEN)
        assert route.call_count == 1

        clock[0] += CACHE_TTL_SECONDS + 1
        await provider.authenticate(TOKEN)
        assert route.call_count == 2

    @respx.mock
    async def test_a_rejection_is_never_cached(self) -> None:
        """A revoked session must not be remembered as valid, and a transient
        failure must not lock a good session out for the whole window."""
        route = respx.get(f"{PROJECT}{USER_PATH}").mock(return_value=httpx.Response(401))
        provider = _provider()
        for _ in range(3):
            with pytest.raises(AuthenticationError):
                await provider.authenticate(TOKEN)
        assert route.call_count == 3


# ------------------------------------------------------ configuration & mode
class TestProviderSelection:
    def test_it_satisfies_the_auth_protocol(self) -> None:
        assert isinstance(_provider(), AuthProvider)

    def test_production_selects_supabase(self) -> None:
        provider = build_auth_provider(_settings(app_env=AppEnv.PRODUCTION))
        assert provider.name == "supabase"
        assert isinstance(provider, SupabaseAuthProvider)

    @pytest.mark.parametrize("missing", [{"supabase_url": None}, {"supabase_anon_key": None}])
    def test_missing_configuration_fails_at_startup(self, missing) -> None:
        """A boot failure, never a 401 that reads to a user as a bad password."""
        with pytest.raises(ValueError, match="SUPABASE_URL"):
            _settings(**missing)

    def test_the_provider_itself_also_refuses_to_construct_unconfigured(self) -> None:
        bare = Settings(database_url="postgresql+asyncpg://localhost/test")
        with pytest.raises(RuntimeError, match="SUPABASE_URL"):
            SupabaseAuthProvider(bare)


class TestDevStubIsUntouched:
    """The offline demo must keep working exactly as before."""

    def test_development_still_gets_the_dev_stub(self) -> None:
        settings = Settings(
            database_url="postgresql+asyncpg://localhost/test", auth_provider="dev_stub"
        )
        provider = build_auth_provider(settings)
        assert provider.name == "dev_stub"
        assert isinstance(provider, DevStubAuthProvider)

    async def test_it_still_needs_no_credential_and_no_network(self) -> None:
        settings = Settings(
            database_url="postgresql+asyncpg://localhost/test", auth_provider="dev_stub"
        )
        identity = await DevStubAuthProvider(settings).authenticate(None)
        assert identity.subject.startswith("dev-stub:")

    def test_it_still_refuses_production(self) -> None:
        settings = Settings(
            app_env=AppEnv.PRODUCTION,
            database_url="postgresql+asyncpg://localhost/test",
            auth_provider="supabase",
            supabase_url=PROJECT,
            supabase_anon_key="anon",
            media_url_secret="test-signing-key",
        )
        with pytest.raises(RuntimeError, match="never run in production"):
            DevStubAuthProvider(settings)

    def test_no_supabase_configuration_is_needed_for_the_offline_demo(self) -> None:
        """The demo must not acquire a dependency on an identity provider."""
        settings = Settings(
            database_url="postgresql+asyncpg://localhost/test",
            auth_provider="dev_stub",
            demo_mode=True,
        )
        assert settings.supabase_url is None
        assert settings.supabase_anon_key is None
        assert build_auth_provider(settings).name == "dev_stub"
