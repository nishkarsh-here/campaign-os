"""Configuration.

`app/config.py` is the only module that reads the environment, so its
validation is the project's single guard against a misconfigured run.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

pytestmark = pytest.mark.unit


class TestProviderCredentialGuards:
    def test_selecting_gemini_without_a_key_fails_at_startup(self) -> None:
        """Better a failed boot than a demo that dies three minutes in."""
        with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
            Settings(llm_provider="gemini", gemini_api_key=None)

    def test_selecting_leonardo_without_a_key_fails(self) -> None:
        with pytest.raises(ValidationError, match="LEONARDO_API_KEY"):
            Settings(image_provider="leonardo", leonardo_api_key=None)

    def test_mocks_need_no_credentials(self) -> None:
        settings = Settings(llm_provider="mock", image_provider="mock")
        assert settings.uses_only_mocks


class TestTestEnvironmentIsSealed:
    def test_a_live_provider_is_refused_under_app_env_test(self) -> None:
        with pytest.raises(ValidationError, match="requires mock providers"):
            Settings(app_env="test", llm_provider="gemini", gemini_api_key="k")


class TestDerivedValues:
    def test_alembic_url_uses_psycopg_not_psycopg2(self) -> None:
        """A bare postgresql:// makes SQLAlchemy reach for psycopg2, which is
        not installed; the checkpointer needs the bare form, so it is derived
        rather than configured twice."""
        settings = Settings(database_url_sync="postgresql://u@h:5432/db")
        assert settings.alembic_url == "postgresql+psycopg://u@h:5432/db"

    def test_an_explicit_driver_is_left_alone(self) -> None:
        settings = Settings(database_url_sync="postgresql+psycopg2://u@h:5432/db")
        assert settings.alembic_url == "postgresql+psycopg2://u@h:5432/db"

    def test_cors_origins_split_into_a_list(self) -> None:
        settings = Settings(cors_origins="http://a.test, http://b.test")
        assert settings.cors_origin_list == ["http://a.test", "http://b.test"]

    def test_upload_limit_converts_to_bytes(self) -> None:
        assert Settings(max_upload_mb=3).max_upload_bytes == 3 * 1024 * 1024


class TestMockFailureMode:
    def test_a_known_mode_is_accepted(self) -> None:
        assert Settings(mock_failure_mode="timeout").mock_failure_mode == "timeout"

    def test_an_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MOCK_FAILURE_MODE"):
            Settings(mock_failure_mode="explode")


class TestTheExampleEnvironmentMatchesSettings:
    """`.env.example` is the deployment contract.

    A variable in `Settings` that nobody documented is a setting operators
    cannot find; a variable in the example that `Settings` does not read is
    worse — it is a knob that appears to work and does nothing. Both have
    happened here, so both are asserted.
    """

    @staticmethod
    def _declared() -> set[str]:
        import re
        from pathlib import Path

        example = Path(__file__).resolve().parents[2] / ".env.example"
        return {
            m.group(1).lower()
            for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", example.read_text(), re.M)
        }

    def test_every_setting_is_documented(self) -> None:
        missing = set(Settings.model_fields) - self._declared()
        assert not missing, f"undocumented settings: {sorted(missing)}"

    def test_the_example_declares_no_phantom_knobs(self) -> None:
        """`LANGGRAPH_STRICT_MSGPACK` sat here for several milestones looking
        like a security control. Nothing read it."""
        phantom = self._declared() - set(Settings.model_fields)
        assert not phantom, f"variables nothing reads: {sorted(phantom)}"
