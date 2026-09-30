"""The documented deployment actually boots.

Audit findings DOC-4, DOC-5 and BG-8. Three separate defects met in one place:

* `DEPLOYMENT.md` §7's "Minimum for a production deploy" was missing
  `SUPABASE_ANON_KEY`, so `Settings` refused it outright;
* it then selected `STORAGE_PROVIDER=supabase`, which §5 of the same document
  says is a Protocol seam with no adapter in this build;
* and §5's claim that selecting one "fails at startup" was only true of the
  reasoning and embedding providers. Storage, image and search were constructed
  per request, so the process booted, `/v1/health` said `ok`, and the failure
  arrived at the first upload.

So the environment block in the document is executed here rather than read. If
someone edits §7, this fails.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import AppEnv, Settings
from app.providers.registry import (
    ProviderNotConfigured,
    assert_providers_are_built,
    provider_readiness,
)

pytestmark = pytest.mark.unit

DEPLOYMENT = Path(__file__).resolve().parents[2] / "docs/DEPLOYMENT.md"

#: Values for the placeholders the document writes as `…`. Nothing secret, and
#: nothing that reaches a network: every provider is constructed offline.
PLACEHOLDERS = {
    # Not localhost: production refuses a database URL that was never changed
    # from its default, and these stand in for a real managed instance.
    "DATABASE_URL": "postgresql+asyncpg://user@db.example.com:5432/campaign_os",
    "DATABASE_URL_SYNC": "postgresql://user@db.example.com:5432/campaign_os",
    "MEDIA_URL_SECRET": "x" * 43,
    "SUPABASE_URL": "https://project.supabase.co",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    "GEMINI_API_KEY": "gemini-key",
    # Whatever the document names, pointed somewhere writable: constructing
    # the local provider creates its root, and a test must not write to the
    # deployment path the document illustrates.
    "LOCAL_STORAGE_DIR": tempfile.mkdtemp(prefix="campaign-os-deploy-doc-"),
}


def _documented_env(heading: str) -> dict[str, str]:
    """The `KEY=value` lines of the first fenced block under a heading.

    Matched on the heading's *text*, not its number: sections get renumbered
    when one is inserted, and a test that breaks on that is reporting the wrong
    thing.
    """
    text = DEPLOYMENT.read_text()
    matches = [line for line in text.splitlines() if heading in line]
    assert matches, f"no heading containing {heading!r}"
    body = text.split(matches[0], 1)[1]
    block = body.split("```bash", 1)[1].split("```", 1)[0]
    env: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match:
            key, value = match.group(1), match.group(2).strip()
            if key == "LOCAL_STORAGE_DIR" or value in {"", "…"}:
                env[key] = PLACEHOLDERS.get(key, value)
            else:
                env[key] = value
    return env


def _settings_from(env: dict[str, str]) -> Settings:
    return Settings(**{key.lower(): value for key, value in env.items()})


class TestTheDocumentedProductionEnvironment:
    def test_the_block_was_actually_found(self) -> None:
        """Guards the test: a renamed heading would make everything below pass
        against an empty dictionary."""
        env = _documented_env("Minimum for a production deploy")
        assert "DATABASE_URL" in env
        assert env.get("APP_ENV") == "production"
        assert len(env) >= 8, env

    def test_it_builds_settings(self) -> None:
        """The first failure: `AUTH_PROVIDER=supabase` requires the anon key,
        and the block did not list it."""
        settings = _settings_from(_documented_env("Minimum for a production deploy"))
        assert settings.app_env == "production"

    def test_every_provider_it_selects_has_an_adapter(self) -> None:
        """The second failure: `STORAGE_PROVIDER=supabase` has no module."""
        settings = _settings_from(_documented_env("Minimum for a production deploy"))
        assert_providers_are_built(settings)

    def test_it_sets_the_signing_key_production_requires(self) -> None:
        env = _documented_env("Minimum for a production deploy")
        assert "MEDIA_URL_SECRET" in env, (
            "two instances with two generated keys reject each other's media links"
        )

    def test_it_sets_both_supabase_keys_auth_requires(self) -> None:
        env = _documented_env("Minimum for a production deploy")
        assert {"SUPABASE_URL", "SUPABASE_ANON_KEY"} <= set(env)


class TestTheDocumentedDemoEnvironment:
    def test_the_demo_block_builds_and_its_providers_exist(self) -> None:
        env = {
            "database_url": PLACEHOLDERS["DATABASE_URL"],
            "database_url_sync": PLACEHOLDERS["DATABASE_URL_SYNC"],
            **{k.lower(): v for k, v in _documented_env("Demonstration deploy").items()},
        }
        settings = Settings(**env)
        assert settings.demo_mode is True
        assert_providers_are_built(settings)


class TestAnUnbuiltProviderIsRefusedAtStartup:
    """What §5 has always claimed. It is now true of all five seams."""

    @staticmethod
    def _production(**overrides: str) -> Settings:
        env = _documented_env("Minimum for a production deploy")
        env.update(overrides)
        return _settings_from(env)

    def test_supabase_storage_is_refused(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="STORAGE_PROVIDER=supabase"):
            assert_providers_are_built(self._production(STORAGE_PROVIDER="supabase"))

    def test_leonardo_images_are_refused(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="IMAGE_PROVIDER=leonardo"):
            assert_providers_are_built(
                self._production(IMAGE_PROVIDER="leonardo", LEONARDO_API_KEY="k")
            )

    def test_tavily_search_is_refused(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="SEARCH_PROVIDER=tavily"):
            assert_providers_are_built(
                self._production(SEARCH_PROVIDER="tavily", TAVILY_API_KEY="k")
            )

    def test_the_refusal_points_at_the_document_that_lists_what_is_built(self) -> None:
        with pytest.raises(ProviderNotConfigured, match=r"DEPLOYMENT\.md"):
            assert_providers_are_built(self._production(STORAGE_PROVIDER="supabase"))


class TestReadinessIsPerSeam:
    def test_every_seam_is_reported(self) -> None:
        """A seam nobody listed would boot unverified, which is the defect."""
        settings = _settings_from(_documented_env("Minimum for a production deploy"))
        assert {status.kind for status in provider_readiness(settings)} == {
            "llm",
            "image",
            "embedding",
            "storage",
            "search",
            # Auth is a different registry answering a different question
            # (ADR-016), and is reported here anyway because readiness is a
            # deployment question rather than an architectural one.
            "auth",
        }

    def test_one_unbuilt_seam_does_not_hide_the_built_ones(self) -> None:
        env = _documented_env("Minimum for a production deploy")
        env["STORAGE_PROVIDER"] = "supabase"
        statuses = {s.kind: s.built for s in provider_readiness(_settings_from(env))}

        assert statuses["storage"] is False
        assert statuses["llm"] is True

    def test_an_unbuilt_seam_carries_the_reason(self) -> None:
        env = _documented_env("Minimum for a production deploy")
        env["STORAGE_PROVIDER"] = "supabase"
        storage = next(s for s in provider_readiness(_settings_from(env)) if s.kind == "storage")

        assert storage.reason == "ModuleNotFoundError"


class TestAnAdapterThatCannotStartIsADifferentSentence:
    """ "No such adapter" and "that adapter could not start" are different
    mistakes with different fixes, so they do not share a message."""

    def test_an_unwritable_storage_root_is_refused_and_named_as_such(self) -> None:
        env = _documented_env("Minimum for a production deploy")
        env["LOCAL_STORAGE_DIR"] = "/campaign-os-not-writable/storage"

        with pytest.raises(ProviderNotConfigured, match="Could not initialise") as caught:
            assert_providers_are_built(_settings_from(env))

        assert "No adapter in this build" not in str(caught.value)


class TestProductionRefusesConfigurationThatIsUnsafeRatherThanAbsent:
    """`APP_ENV=production` plus a value that is valid everywhere else.

    Separate from the missing-credential checks: nothing here is absent. Each is
    a value somebody supplied, that parses, and that means something dangerous
    or self-contradictory in production — so the deploy comes up looking healthy,
    which is the whole problem.
    """

    @staticmethod
    def _production(**overrides: object) -> Settings:
        env = _documented_env("Minimum for a production deploy")
        settings = {key.lower(): value for key, value in env.items()}
        settings.update(overrides)
        return Settings(**settings)  # type: ignore[arg-type]

    def test_the_documented_environment_is_accepted(self) -> None:
        """The control. Every refusal below has to be about the override."""
        assert self._production().app_env is AppEnv.PRODUCTION

    def test_wildcard_cors_is_refused(self) -> None:
        """`*` with `allow_credentials=True` is rejected by every browser, so it
        does not even do the unsafe thing it appears to do — it fails
        confusingly. Named origins only."""
        with pytest.raises(ValidationError, match=r"CORS_ORIGINS=\* is refused"):
            self._production(cors_origins="*")

    def test_empty_cors_is_refused(self) -> None:
        """The opposite mistake, equally silent: `curl` works perfectly and no
        browser can reach the API at all."""
        with pytest.raises(ValidationError, match="CORS_ORIGINS is empty"):
            self._production(cors_origins="")

    def test_a_plain_http_origin_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must be https in production"):
            self._production(cors_origins="http://app.example.com")

    def test_several_named_https_origins_are_accepted(self) -> None:
        settings = self._production(
            cors_origins="https://app.example.com,https://admin.example.com"
        )
        assert settings.cors_origin_list == ["https://app.example.com", "https://admin.example.com"]

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
    def test_a_database_url_left_at_localhost_is_refused(self, host: str) -> None:
        with pytest.raises(ValidationError, match="DATABASE_URL still points at localhost"):
            self._production(database_url=f"postgresql+asyncpg://u@{host}:5432/campaign_os")

    def test_the_sync_database_url_is_checked_too(self) -> None:
        """Alembic uses it, so a deploy that migrated the wrong database is
        exactly as broken and rather harder to see."""
        with pytest.raises(ValidationError, match="DATABASE_URL_SYNC still points at localhost"):
            self._production(database_url_sync="postgresql://u@localhost:5432/campaign_os")

    def test_demo_mode_is_refused_in_production(self) -> None:
        """Two different declarations. `DEMO_MODE` forces mock providers, so a
        production instance in demo mode serves mock output to real users while
        reporting itself as production."""
        with pytest.raises(ValidationError, match="DEMO_MODE=true is a demonstration"):
            self._production(demo_mode=True)

    def test_the_refusal_names_every_problem_at_once(self) -> None:
        """One deploy, one error listing everything wrong with it — rather than
        an operator fixing one variable, redeploying, and finding the next."""
        with pytest.raises(ValidationError) as caught:
            self._production(cors_origins="*", demo_mode=True)
        message = str(caught.value)
        assert "CORS_ORIGINS" in message
        assert "DEMO_MODE" in message


class TestTheDevStubCannotReachProduction:
    """The deployment mistake with the worst consequence.

    `DevStubAuthProvider` authenticates **every caller as the same user** and its
    constructor refuses to run under `APP_ENV=production` — its docstring says
    that guard "makes that a startup failure rather than a silent hole". Nothing
    constructed it at startup, so the process booted, `/v1/health` answered `ok`
    with `auth: dev_stub`, and the guard fired as a `500` on the first
    authenticated request.
    """

    @staticmethod
    def _production(**overrides: object) -> Settings:
        env = _documented_env("Minimum for a production deploy")
        settings = {key.lower(): value for key, value in env.items()}
        settings.update(overrides)
        return Settings(**settings)  # type: ignore[arg-type]

    def test_it_is_refused_at_startup(self) -> None:
        with pytest.raises(ProviderNotConfigured, match="AUTH_PROVIDER=dev_stub"):
            assert_providers_are_built(self._production(auth_provider="dev_stub"))

    def test_it_is_reported_as_an_adapter_that_could_not_start(self) -> None:
        """Not "no such adapter" — the adapter exists and refused. Different
        mistake, different fix."""
        with pytest.raises(ProviderNotConfigured, match="Could not initialise") as caught:
            assert_providers_are_built(self._production(auth_provider="dev_stub"))
        assert "No adapter in this build" not in str(caught.value)

    def test_auth_is_one_of_the_seams_readiness_reports(self) -> None:
        """A seam nobody listed boots unverified, which is how this was missed."""
        kinds = {status.kind for status in provider_readiness(self._production())}
        assert kinds == {"llm", "image", "embedding", "storage", "search", "auth"}

    def test_the_dev_stub_still_works_outside_production(self) -> None:
        """The offline demo must keep running with no identity provider, forever
        (CLAUDE.md §3.5). The guard is about `APP_ENV`, not about the stub."""
        settings = Settings(
            app_env="development",
            auth_provider="dev_stub",
            llm_provider="mock",
            image_provider="mock",
            embedding_provider="mock",
            storage_provider="local",
            local_storage_dir=PLACEHOLDERS["LOCAL_STORAGE_DIR"],
        )
        assert_providers_are_built(settings)
        assert all(status.built for status in provider_readiness(settings))


class TestTheRecommendedFirstDeployment:
    """§8 — real auth, real database, mock model providers.

    The configuration this document tells someone to deploy and verify first, so
    it is executed here rather than read. It exercises every hosting path that
    can go wrong — sign-in, CORS, signed media, the volume — while spending
    nothing and depending on no external model API.
    """

    @staticmethod
    def _env() -> dict[str, str]:
        return _documented_env("First deployment")

    def test_the_block_was_found(self) -> None:
        env = self._env()
        assert env.get("APP_ENV") == "production"
        assert len(env) >= 12, env

    def test_it_builds_settings_and_every_provider_constructs(self) -> None:
        settings = _settings_from(self._env())
        assert_providers_are_built(settings)

    def test_it_spends_nothing(self) -> None:
        """The reason this is the first deployment rather than the second. Also
        the standing instruction for this verification: no Gemini calls."""
        env = self._env()
        assert env["LLM_PROVIDER"] == "mock"
        assert env["IMAGE_PROVIDER"] == "mock"
        assert env["EMBEDDING_PROVIDER"] == "mock"
        assert env["SEARCH_PROVIDER"] == "none"
        assert "GEMINI_API_KEY" not in env

    def test_it_is_a_production_instance_not_a_declared_demonstration(self) -> None:
        """`DEMO_MODE` would force mock providers *and* put a badge on the
        interface. This instance uses mock providers and is not a demo — the two
        are different statements, and production refuses the second."""
        settings = _settings_from(self._env())
        assert settings.demo_mode is False
        assert settings.app_env is AppEnv.PRODUCTION

    def test_it_uses_real_authentication(self) -> None:
        settings = _settings_from(self._env())
        assert settings.auth_provider == "supabase"

    def test_it_uses_the_only_storage_provider_that_exists(self) -> None:
        settings = _settings_from(self._env())
        assert settings.storage_provider == "local"

    def test_switching_to_real_models_later_needs_no_other_change(self) -> None:
        """The claim the document makes about going live afterwards: three
        variables and a key. Asserted so it cannot quietly stop being true."""
        env = self._env() | {
            "LLM_PROVIDER": "gemini",
            "IMAGE_PROVIDER": "gemini",
            "EMBEDDING_PROVIDER": "gemini",
            "GEMINI_API_KEY": "key-from-the-operator",
        }
        assert_providers_are_built(_settings_from(env))
