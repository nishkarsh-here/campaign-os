"""Configuration — the only place the environment is read.

Nothing else in the codebase touches `os.environ`. That is what makes provider
selection a one-line change and what keeps secrets out of business logic.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PRODUCT_NAME = "campaign-os"


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- runtime ---------------------------------------------------------
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # --- database --------------------------------------------------------
    #: Application DSN (SQLAlchemy async, asyncpg driver).
    database_url: str = "postgresql+asyncpg://localhost:5432/campaign_os"
    #: Plain libpq DSN. Used verbatim by the LangGraph Postgres checkpointer,
    #: which talks to psycopg directly and does not understand SQLAlchemy's
    #: "+driver" form. Alembic derives its own URL from this — see below.
    database_url_sync: str = "postgresql://localhost:5432/campaign_os"

    # --- provider selection ----------------------------------------------
    llm_provider: str = "mock"
    image_provider: str = "mock"
    #: Providers a "generate creatives" request fans out to, comma separated.
    #: Empty means "just `image_provider`" — so a single-provider setup needs
    #: no extra configuration, and a multi-provider demo is one env var.
    image_providers: str = ""
    #: Plates each provider returns per batch. One by default: the point of
    #: multi-provider generation is comparing *providers*, and four
    #: near-identical plates from each is spend without information. Raise it
    #: when variants from one provider are what you actually want to compare.
    generation_images_per_job: int = Field(default=1, ge=1, le=4)
    embedding_provider: str = "mock"
    storage_provider: str = "local"
    search_provider: str = "none"

    # --- credentials -------------------------------------------------------
    gemini_api_key: str | None = None
    gemini_text_model: str = "gemini-2.5-pro"
    gemini_image_model: str = "gemini-2.5-flash-image"
    gemini_embedding_model: str = "gemini-embedding-001"
    leonardo_api_key: str | None = None
    leonardo_model_id: str | None = None
    tavily_api_key: str | None = None

    # --- storage -----------------------------------------------------------
    local_storage_dir: str = "./storage"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "campaign-assets"

    # --- auth ---------------------------------------------------------------
    auth_provider: str = "dev_stub"
    dev_stub_user_email: str = "demo@campaign-os.local"
    dev_stub_org_slug: str = "demo-org"

    # --- limits --------------------------------------------------------------
    max_upload_mb: int = Field(default=15, ge=1, le=100)
    allowed_upload_mime: str = "image/png,image/jpeg,image/webp,application/pdf"
    generation_timeout_s: int = 120
    llm_timeout_s: int = 60
    #: Revision iterations. Distinct from the interview budget below, so a long
    #: interview cannot exhaust the ability to revise (ARCHITECTURE_REVIEW C-2).
    max_graph_iterations: int = Field(default=8, ge=1, le=50)
    #: Hard cap on interview questions. An interview that will not end is worse
    #: than one that proceeds on stated assumptions.
    max_interview_turns: int = Field(default=8, ge=1, le=30)

    # --- mock provider behaviour ------------------------------------------------
    #: Forces the mock providers to fail, so error paths are tested rather than
    #: assumed (TESTING.md). "none" is normal deterministic behaviour.
    mock_failure_mode: str = "none"
    #: Artificial delay per mock generation. Zero in tests; a second or two
    #: locally makes the PENDING -> RUNNING -> COMPLETED transitions visible
    #: in the UI instead of everything finishing before the first poll.
    mock_image_latency_seconds: float = 0.0

    # --- demo -------------------------------------------------------------------
    #: Marks this instance as a demonstration instance.
    #:
    #: Not the same thing as "the providers happen to be mock". This is a
    #: *declaration* — it is enforced below, so a demo instance cannot quietly
    #: be talking to a paid provider or depending on a network that may not be
    #: there when it matters. It is surfaced on `/v1/health` so the interface
    #: can say so out loud rather than leaving a viewer to guess whether what
    #: they are looking at is real.
    demo_mode: bool = False

    # --- observability ---------------------------------------------------------
    sentry_dsn: str | None = None

    # ------------------------------------------------------------------ derived
    @property
    def alembic_url(self) -> str:
        """`database_url_sync` as SQLAlchemy needs it.

        A bare `postgresql://` makes SQLAlchemy reach for psycopg2, which this
        project does not install — we use psycopg 3. Deriving the driver here
        keeps one canonical DSN in the environment instead of two that can
        drift apart.
        """
        if "+" in self.database_url_sync.split("://", 1)[0]:
            return self.database_url_sync
        return self.database_url_sync.replace("postgresql://", "postgresql+psycopg://", 1)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_mime_set(self) -> set[str]:
        return {m.strip() for m in self.allowed_upload_mime.split(",") if m.strip()}

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def image_provider_list(self) -> tuple[str, ...]:
        """The providers to generate with, in order.

        Deduplicated and order-preserving: a repeated name in the env would
        otherwise create two jobs for one provider and charge twice.
        """
        names = [n.strip() for n in self.image_providers.split(",") if n.strip()]
        if not names:
            names = [self.image_provider]
        return tuple(dict.fromkeys(names))

    @property
    def uses_only_mocks(self) -> bool:
        return self.llm_provider == "mock" and self.image_provider == "mock"

    @field_validator("image_providers")
    @classmethod
    def _known_image_providers(cls, v: str) -> str:
        from app.providers.registry import IMAGE_PROVIDERS

        unknown = {n.strip() for n in v.split(",") if n.strip()} - set(IMAGE_PROVIDERS)
        if unknown:
            raise ValueError(
                f"IMAGE_PROVIDERS names unknown providers: {sorted(unknown)}. "
                f"Available: {', '.join(IMAGE_PROVIDERS)}"
            )
        return v

    @field_validator("mock_failure_mode")
    @classmethod
    def _known_failure_mode(cls, v: str) -> str:
        allowed = {"none", "timeout", "malformed", "rate_limit", "unavailable", "blocked"}
        if v not in allowed:
            raise ValueError(f"MOCK_FAILURE_MODE must be one of {sorted(allowed)}")
        return v

    @model_validator(mode="after")
    def _credentials_present_for_selected_providers(self) -> Settings:
        """Fail at startup, not at the first user request.

        A missing key is a configuration mistake; discovering it three minutes
        into a demo is the worst possible time.
        """
        missing: list[str] = []
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            missing.append("GEMINI_API_KEY (LLM_PROVIDER=gemini)")
        if self.image_provider == "gemini" and not self.gemini_api_key:
            missing.append("GEMINI_API_KEY (IMAGE_PROVIDER=gemini)")
        if self.image_provider == "leonardo" and not self.leonardo_api_key:
            missing.append("LEONARDO_API_KEY (IMAGE_PROVIDER=leonardo)")
        if self.embedding_provider == "gemini" and not self.gemini_api_key:
            missing.append("GEMINI_API_KEY (EMBEDDING_PROVIDER=gemini)")
        if self.search_provider == "tavily" and not self.tavily_api_key:
            missing.append("TAVILY_API_KEY (SEARCH_PROVIDER=tavily)")
        if self.storage_provider == "supabase" and not (
            self.supabase_url and self.supabase_service_role_key
        ):
            missing.append("SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (STORAGE_PROVIDER=supabase)")
        if missing:
            raise ValueError("Missing configuration: " + "; ".join(missing))

        # A demo instance must be self-contained. The whole point of the mode
        # is that the demonstration cannot be broken by a dead key, a rate
        # limit or a conference network — so declaring it while pointing at a
        # live provider is a contradiction, and it fails at startup rather
        # than three minutes into a presentation.
        if self.demo_mode:
            live = [
                f"{name}={value}"
                for name, value in (
                    ("LLM_PROVIDER", self.llm_provider),
                    ("IMAGE_PROVIDER", self.image_provider),
                    ("EMBEDDING_PROVIDER", self.embedding_provider),
                )
                if value != "mock"
            ]
            if live:
                raise ValueError(
                    "DEMO_MODE=true requires mock providers so the demonstration "
                    "cannot depend on an external service; got " + ", ".join(live)
                )

        # Tests must never reach a real provider or spend credit (TESTING.md).
        if self.app_env is AppEnv.TEST:
            live = [
                f"{n}={v}"
                for n, v in (
                    ("LLM_PROVIDER", self.llm_provider),
                    ("IMAGE_PROVIDER", self.image_provider),
                    ("EMBEDDING_PROVIDER", self.embedding_provider),
                )
                if v != "mock"
            ]
            if live:
                raise ValueError("APP_ENV=test requires mock providers; got " + ", ".join(live))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
