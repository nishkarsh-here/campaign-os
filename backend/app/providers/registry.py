"""Configuration -> concrete providers.

The only module that knows which vendors exist. Everything else receives a
Protocol (ARCHITECTURE ADR-005).

Implementations are imported lazily inside the factories so that selecting
`mock` never imports a vendor SDK — which is what lets the whole test suite and
the offline demo run without any provider package being importable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.base import (
    EmbeddingProvider,
    ImageProvider,
    LLMProvider,
    PromptAdapter,
    SearchProvider,
    StorageProvider,
)


class ProviderNotConfigured(RuntimeError):
    """A provider name in the environment that we have no implementation for.
    Raised at startup with the list of valid names."""


def _unknown(kind: str, name: str, known: tuple[str, ...]) -> ProviderNotConfigured:
    return ProviderNotConfigured(f"Unknown {kind} provider {name!r}. Available: {', '.join(known)}")


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    match s.llm_provider:
        case "mock":
            from app.providers.mock.llm import MockLLMProvider

            return MockLLMProvider(s.mock_failure_mode)
        case "gemini":
            from app.providers.gemini.llm import GeminiLLMProvider

            return GeminiLLMProvider(s)
        case other:
            raise _unknown("LLM", other, ("mock", "gemini"))


def build_image_provider(
    settings: Settings | None = None, name: str | None = None
) -> ImageProvider:
    """`name` overrides configuration so the generation router can fan out
    across providers, or fall back to the next one, without re-reading env."""
    s = settings or get_settings()
    match name or s.image_provider:
        case "mock":
            from app.providers.mock.image import MockImageProvider

            return MockImageProvider(
                s.mock_failure_mode, latency_seconds=s.mock_image_latency_seconds
            )
        case "gemini":
            from app.providers.gemini.image import GeminiImageProvider

            return GeminiImageProvider(s)
        case "leonardo":
            from app.providers.leonardo.image import LeonardoImageProvider

            return LeonardoImageProvider(s)
        case other:
            raise _unknown("image", other, IMAGE_PROVIDERS)


#: Every image provider this build can talk to. One list, used for validation,
#: for the error message above, and for fanning out — so adding a provider
#: cannot leave one of the three behind.
IMAGE_PROVIDERS: tuple[str, ...] = ("mock", "gemini", "leonardo")


def build_prompt_adapter(
    settings: Settings | None = None, name: str | None = None
) -> PromptAdapter:
    """The prompt adapter for one image provider.

    Paired with `build_image_provider` by name: a provider that can generate
    must also be able to be asked, and splitting the two registries would let
    them drift apart.
    """
    s = settings or get_settings()
    match name or s.image_provider:
        case "mock":
            from app.providers.mock.prompt import MockPromptAdapter

            return MockPromptAdapter()
        case "gemini":
            from app.providers.gemini.prompt import GeminiPromptAdapter

            return GeminiPromptAdapter(s.gemini_image_model)
        case "leonardo":
            from app.providers.leonardo.prompt import LeonardoPromptAdapter

            return LeonardoPromptAdapter(s.leonardo_model_id or "leonardo-phoenix")
        case other:
            raise _unknown("prompt", other, IMAGE_PROVIDERS)


def build_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    s = settings or get_settings()
    match s.embedding_provider:
        case "mock":
            from app.providers.mock.embedding import MockEmbeddingProvider

            return MockEmbeddingProvider(s.mock_failure_mode)
        case "gemini":
            from app.providers.gemini.embedding import GeminiEmbeddingProvider

            return GeminiEmbeddingProvider(s)
        case other:
            raise _unknown("embedding", other, ("mock", "gemini"))


def build_storage_provider(settings: Settings | None = None) -> StorageProvider:
    s = settings or get_settings()
    match s.storage_provider:
        case "local":
            from app.providers.local.storage import LocalStorageProvider

            return LocalStorageProvider(s.local_storage_dir)
        case "supabase":
            from app.providers.supabase.storage import SupabaseStorageProvider

            return SupabaseStorageProvider(s)
        case other:
            raise _unknown("storage", other, ("local", "supabase"))


def build_search_provider(settings: Settings | None = None) -> SearchProvider:
    s = settings or get_settings()
    match s.search_provider:
        case "none":
            from app.providers.mock.search import NullSearchProvider

            return NullSearchProvider()
        case "tavily":
            from app.providers.tavily.search import TavilySearchProvider

            return TavilySearchProvider(s)
        case other:
            raise _unknown("search", other, ("none", "tavily"))


class Providers:
    """The bundle injected into graph nodes and services.

    Nodes receive this, never the registry — so a node cannot reach for a
    provider it did not declare, and tests substitute the whole bundle.
    """

    def __init__(
        self,
        llm: LLMProvider,
        image: ImageProvider,
        embedding: EmbeddingProvider,
        storage: StorageProvider,
        search: SearchProvider,
    ) -> None:
        self.llm = llm
        self.image = image
        self.embedding = embedding
        self.storage = storage
        self.search = search


@lru_cache
def get_providers() -> Providers:
    s = get_settings()
    return Providers(
        llm=build_llm_provider(s),
        image=build_image_provider(s),
        embedding=build_embedding_provider(s),
        storage=build_storage_provider(s),
        search=build_search_provider(s),
    )


def assert_embedding_dimensions(provider: EmbeddingProvider) -> None:
    """Fail at startup if the provider's width disagrees with the column.

    `brand_chunks.embedding` is `vector(1536)`, pinned by migration 002.
    A provider of a different width would either error on every insert or —
    worse, if it silently truncated — return retrieval garbage that looks like
    a quality problem rather than a configuration one (ROADMAP risk R-4).
    """
    from app.db.models import EMBEDDING_DIMENSIONS

    if provider.dimensions != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"EMBEDDING_PROVIDER {provider.name!r} produces {provider.dimensions}-dimension "
            f"vectors, but brand_chunks.embedding is vector({EMBEDDING_DIMENSIONS}). "
            "Changing the embedding model requires a migration and a re-embed."
        )


# ---------------------------------------------------------------------------
# Readiness. Audit findings DOC-5 / BG-8.
# ---------------------------------------------------------------------------
#
# `DEPLOYMENT.md` §5 states that selecting a provider this build has no adapter
# for "fails at startup". That was true of the reasoning and embedding providers,
# which the lifespan constructs, and false of storage, image and search, which
# nothing constructed until the first request that needed one. So
# `STORAGE_PROVIDER=supabase` booted cleanly, `/v1/health` answered `"status":
# "ok"` with `"storage": "supabase"` — because it echoed the setting — and the
# failure arrived at the first brand-document upload.
#
# A name in a variable is not a capability. Both are fixed here: everything is
# constructed at startup, and health reports what was constructed rather than
# what was asked for.


@dataclass(frozen=True)
class ProviderReadiness:
    """Whether the selected name has an adapter behind it, right now."""

    kind: str
    name: str
    built: bool
    #: The exception type, for an operator. Never the message — a vendor
    #: message is log-side detail (`ProviderError.__init__`).
    reason: str | None = None


#: Every provider seam, with the factory that proves it. Deliberately a table
#: rather than five calls: a seam added later that nobody lists here would boot
#: unverified, which is the defect this fixes.
def _build_auth(settings: Settings) -> object:
    """The auth provider, imported here rather than at module scope.

    `app/auth/` is deliberately a different registry answering a different
    question — "who is this?", never "may they?" (ADR-016) — and that separation
    stands. It appears in this table anyway because **readiness is a deployment
    question, not an architectural one**: an operator asking "did this instance
    come up able to do its job" means all six seams, and splitting the answer
    across two mechanisms is how one of them comes to be forgotten.

    It matters most here. `DevStubAuthProvider.__init__` refuses to run under
    `APP_ENV=production` — it authenticates every caller as the same user — and
    its own docstring says that guard "makes that a startup failure rather than a
    silent hole". Nothing constructed it at startup, so the process booted,
    `/v1/health` answered `ok` with `auth: dev_stub`, and the guard fired as a
    500 on the first authenticated request instead.
    """
    from app.auth.registry import build_auth_provider

    return build_auth_provider(settings)


_SEAMS: tuple[tuple[str, Callable[[Settings], object]], ...] = (
    ("llm", build_llm_provider),
    ("image", build_image_provider),
    ("embedding", build_embedding_provider),
    ("storage", build_storage_provider),
    ("search", build_search_provider),
    ("auth", _build_auth),
)


#: Exception types that mean "this build has no such adapter", as opposed to
#: "the adapter exists and could not start".
_NO_ADAPTER = frozenset({"ModuleNotFoundError", "ImportError", "ProviderNotConfigured"})


def _selected(settings: Settings, kind: str) -> str:
    return str(getattr(settings, f"{kind}_provider"))


def provider_readiness(settings: Settings | None = None) -> list[ProviderReadiness]:
    """Construct every provider and report which ones came up.

    **Nothing here reaches a network.** Constructing an API-backed adapter is an
    import and an object; it never calls the vendor, so `built` says the adapter
    exists and is configured, never that the vendor is up. A live credential is
    only ever proved by using it — the same point ADR-016 makes about tokens and
    §5 makes about model ids.

    It is not quite free of I/O, and deliberately so: `LocalStorageProvider`
    creates its root in `__init__`, so an unwritable `LOCAL_STORAGE_DIR` shows up
    here. That is worth catching at boot rather than at the first upload, for the
    same reason a missing adapter is.
    """
    s = settings or get_settings()
    statuses: list[ProviderReadiness] = []
    for kind, factory in _SEAMS:
        name = _selected(s, kind)
        try:
            factory(s)
        except Exception as exc:  # noqa: BLE001 - reported, never raised here
            statuses.append(
                ProviderReadiness(kind=kind, name=name, built=False, reason=type(exc).__name__)
            )
        else:
            statuses.append(ProviderReadiness(kind=kind, name=name, built=True))
    return statuses


def assert_providers_are_built(settings: Settings | None = None) -> None:
    """Refuse to start when a selected provider has no adapter.

    What §5 already promised. A configuration mistake is worth a container that
    will not start and says why; discovering it at the first upload — or three
    minutes into a demo — is the worst possible time.
    """
    unavailable = [status for status in provider_readiness(settings) if not status.built]
    if not unavailable:
        return

    # Two different mistakes, worth two different sentences. "There is no such
    # adapter" is answered by picking a name §5 lists; "the adapter exists and
    # could not start" is answered by fixing what it needs.
    missing = [s for s in unavailable if s.reason in _NO_ADAPTER]
    broken = [s for s in unavailable if s.reason not in _NO_ADAPTER]
    parts: list[str] = []
    if missing:
        parts.append(
            "No adapter in this build for: "
            + "; ".join(f"{s.kind.upper()}_PROVIDER={s.name}" for s in missing)
            + ". See docs/DEPLOYMENT.md §5 for what is built."
        )
    if broken:
        parts.append(
            "Could not initialise: "
            + "; ".join(f"{s.kind.upper()}_PROVIDER={s.name} ({s.reason})" for s in broken)
            + "."
        )
    raise ProviderNotConfigured(" ".join(parts))
