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
    #: Reasoning model. Stable rather than a `-preview` or a `-latest` alias:
    #: a plan that changes under you between two runs is not reproducible.
    #: Multimodal, because reference analysis, evaluation and the Brand
    #: Guardian all hand this model an image.
    gemini_llm_model: str = "gemini-3.8-flash"
    #: Image generation. Deliberately independent of the reasoning model —
    #: they are different capabilities on different release cadences, and
    #: coupling them means changing one silently changes the other.
    #:
    #: Nano Banana 2. `gemini-2.5-flash-image` is the legacy model and the
    #: documentation now recommends transitioning off it.
    gemini_image_model: str = "gemini-3.1-flash-image"
    gemini_embedding_model: str = "gemini-embedding-001"
    #: Vector width asked of the embedding API, never trimmed afterwards.
    #: Must equal `brand_chunks.embedding`'s declared width, which
    #: `registry.assert_embedding_dimensions` checks at startup. The bounds
    #: are the documented range for the Gemini embedding API.
    gemini_embedding_dimensions: int = Field(default=1536, ge=128, le=3072)
    leonardo_api_key: str | None = None
    leonardo_model_id: str | None = None
    tavily_api_key: str | None = None

    # --- storage -----------------------------------------------------------
    local_storage_dir: str = "./storage"
    supabase_url: str | None = None
    #: The publishable (anon) key. Used only to identify the project when
    #: verifying a user's own token against Supabase Auth — it carries no
    #: privilege of its own, which is why auth does not use the service-role
    #: key below. Safe to expose to a browser; Supabase intends it to be.
    supabase_anon_key: str | None = None
    #: Server-side only, and storage's alone. Never sent by the auth provider.
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "campaign-assets"

    # --- auth ---------------------------------------------------------------
    auth_provider: str = "dev_stub"
    dev_stub_user_email: str = "demo@campaign-os.local"
    dev_stub_org_slug: str = "demo-org"

    # --- media links ---------------------------------------------------------
    #: Signing key for the short-lived links that serve bytes to a browser.
    #:
    #: A browser cannot put `Authorization` or `X-Organization-Id` on an
    #: `<img src>`, so the API mints a signed, expiring, single-row link
    #: instead (`app/api/media_links.py`). Unset means "generate one per
    #: process": no configuration for the offline demo or the tests, and no
    #: shipped default that would be identical on every install. Production
    #: must set it — see the validator below — because two instances with two
    #: ephemeral secrets reject each other's links.
    media_url_secret: str | None = None
    #: How long such a link lives. Long enough to render a page and for a
    #: person to open an image in a new tab; short enough that a link which
    #: leaks into a log or a referrer is worthless by the time anyone reads it.
    media_url_ttl_s: int = Field(default=900, ge=30, le=86_400)

    # --- limits --------------------------------------------------------------
    max_upload_mb: int = Field(default=15, ge=1, le=100)
    allowed_upload_mime: str = "image/png,image/jpeg,image/webp,application/pdf"
    generation_timeout_s: int = 120
    llm_timeout_s: int = 60
    #: Extra attempts after a *retryable* image failure — a timeout, a rate
    #: limit or a 5xx. Never a refusal, a bad request or an unusable payload:
    #: retrying those spends money to receive the same answer.
    #:
    #: One by default, and capped at three, because every attempt is billable.
    #: This is the only retry in the image path; the router's per-provider
    #: fallback is a separate, explicit user-visible action.
    image_max_retries: int = Field(default=1, ge=0, le=3)
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
        # A blank model id reaches the provider as a request for nothing and
        # comes back as an opaque 400 mid-campaign. It is configuration, so it
        # is caught with the rest of the configuration. Whether the id names a
        # model that exists can only be answered by the provider — that is
        # what `scripts/gemini_*_smoke_test.py` are for.
        for selected, provider, model, name in (
            (self.llm_provider, "LLM_PROVIDER", self.gemini_llm_model, "GEMINI_LLM_MODEL"),
            (
                self.image_provider,
                "IMAGE_PROVIDER",
                self.gemini_image_model,
                "GEMINI_IMAGE_MODEL",
            ),
            (
                self.embedding_provider,
                "EMBEDDING_PROVIDER",
                self.gemini_embedding_model,
                "GEMINI_EMBEDDING_MODEL",
            ),
        ):
            if selected == "gemini" and not model.strip():
                missing.append(f"{name} ({provider}=gemini)")
        if self.search_provider == "tavily" and not self.tavily_api_key:
            missing.append("TAVILY_API_KEY (SEARCH_PROVIDER=tavily)")
        if self.storage_provider == "supabase" and not (
            self.supabase_url and self.supabase_service_role_key
        ):
            missing.append("SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (STORAGE_PROVIDER=supabase)")
        # Auth needs the project URL and the publishable key, and deliberately
        # not the service-role key: a standing escalation for a request that
        # already carries the caller's own token would be privilege for
        # nothing. Checked here so a missing key is a boot failure rather than
        # a 401 that looks to the user like a bad password.
        if self.auth_provider == "supabase" and not (self.supabase_url and self.supabase_anon_key):
            missing.append("SUPABASE_URL + SUPABASE_ANON_KEY (AUTH_PROVIDER=supabase)")
        # A per-process signing key works for one instance and silently fails
        # for two: a link minted by one is a bad signature at the other, which
        # presents as images that load on refresh and not before. Configuration
        # mistakes belong at startup, not in an intermittent bug report.
        if self.app_env is AppEnv.PRODUCTION and not self.media_url_secret:
            missing.append("MEDIA_URL_SECRET (APP_ENV=production)")
        if missing:
            raise ValueError("Missing configuration: " + "; ".join(missing))

        if self.app_env is AppEnv.PRODUCTION:
            self._refuse_unsafe_production()

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

    def _refuse_unsafe_production(self) -> None:
        """Settings that are fine anywhere else and wrong under `APP_ENV=production`.

        Separate from the missing-credential list above because these are not
        absences — every one of them is a value that was supplied, is valid, and
        means something dangerous or self-contradictory in production. A deploy
        that comes up on any of them looks healthy, which is the problem.
        """
        wrong: list[str] = []

        # `*` with `allow_credentials=True` is rejected by every browser, so it
        # does not even do the unsafe thing it looks like it does — it fails
        # confusingly instead. Empty is the opposite mistake and just as silent:
        # the API answers `curl` perfectly and no browser can reach it.
        origins = self.cors_origin_list
        if not origins:
            wrong.append("CORS_ORIGINS is empty, so no browser origin may call this API")
        elif "*" in origins:
            wrong.append(
                "CORS_ORIGINS=* is refused in production. Name the frontend origin, "
                "e.g. https://app.example.com"
            )
        else:
            insecure = [o for o in origins if o.startswith("http://")]
            if insecure:
                wrong.append("CORS_ORIGINS must be https in production; got " + ", ".join(insecure))

        # A default database URL in production points at a database that is not
        # there — or, worse, at one that is. Either way the deploy did not set it.
        for name, url in (
            ("DATABASE_URL", self.database_url),
            ("DATABASE_URL_SYNC", self.database_url_sync),
        ):
            host = url.split("://", 1)[-1]
            if "localhost" in host or "127.0.0.1" in host:
                wrong.append(f"{name} still points at localhost")

        # Two different declarations. DEMO_MODE forces mock providers so a
        # demonstration cannot be broken by a network — which means a
        # "production" instance in demo mode serves mock output to real users
        # while reporting itself as production.
        if self.demo_mode:
            wrong.append("DEMO_MODE=true is a demonstration instance, not a production one")

        if wrong:
            raise ValueError("Unsafe for APP_ENV=production: " + "; ".join(wrong))


@lru_cache
def get_settings() -> Settings:
    return Settings()
