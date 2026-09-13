"""Configuration -> concrete providers.

The only module that knows which vendors exist. Everything else receives a
Protocol (ARCHITECTURE ADR-005).

Implementations are imported lazily inside the factories so that selecting
`mock` never imports a vendor SDK — which is what lets the whole test suite and
the offline demo run without any provider package being importable.
"""

from __future__ import annotations

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
