"""FastAPI application factory.

Wiring only. Nothing here knows about brands, campaigns or providers beyond
selecting them — the app is assembled from parts that are each testable alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routers import (
    brand_brain,
    brands,
    campaigns,
    composition,
    health,
    me,
    organizations,
    projects,
)
from app.config import PRODUCT_NAME, AppEnv, Settings, get_settings
from app.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    log.info(
        "startup",
        env=str(settings.app_env),
        llm=settings.llm_provider,
        image=settings.image_provider,
        storage=settings.storage_provider,
        auth=settings.auth_provider,
    )
    # LangGraph's checkpoint tables. Created here rather than per-request:
    # `setup()` issues CREATE INDEX CONCURRENTLY, which waits for every open
    # transaction, so calling it inside a request deadlocks against that
    # request's own session.
    try:
        from app.services.campaigns import ensure_checkpoint_tables

        await ensure_checkpoint_tables(settings)
    except Exception as exc:  # noqa: BLE001
        log.error("checkpoint_setup_failed", error=type(exc).__name__)

    # A provider whose vector width disagrees with the column is a
    # configuration error; catch it here rather than at the first retrieval.
    from app.providers.registry import assert_embedding_dimensions, build_embedding_provider

    assert_embedding_dimensions(build_embedding_provider(settings))

    # The dev stub asserts an identity but provisions nothing. Give that
    # identity a workspace here, once, so the request path stays identical in
    # every environment (see app/services/bootstrap.py).
    if settings.auth_provider == "dev_stub":
        from app.db.session import get_sessionmaker
        from app.services.bootstrap import ensure_dev_workspace

        try:
            async with get_sessionmaker()() as session:
                await ensure_dev_workspace(session, settings)
        except Exception as exc:  # noqa: BLE001
            # A missing database must not stop the process from starting —
            # /health reports it, which is far easier to diagnose than a
            # container that exits during boot.
            log.error("dev_workspace_bootstrap_failed", error=type(exc).__name__)
    # Anything a previous process left in flight. Without this, a restart
    # during generation leaves a row RUNNING forever and the interface polls a
    # spinner that will never resolve (app/services/reconcile.py).
    try:
        from app.db.session import get_sessionmaker
        from app.services.reconcile import reconcile_interrupted_jobs

        async with get_sessionmaker()() as session:
            moved = await reconcile_interrupted_jobs(session, settings)
        if moved:
            log.info("startup_reconciled", rows=moved)
    except Exception as exc:  # noqa: BLE001
        # Same reasoning as the bootstrap above: a database that is not there
        # yet must not stop the process from starting. /health reports it.
        log.error("reconcile_failed", error=type(exc).__name__)

    yield
    log.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.app_env is AppEnv.PRODUCTION)

    app = FastAPI(
        title=PRODUCT_NAME,
        version="0.1.0",
        summary="AI marketing & branding orchestration platform",
        docs_url="/v1/docs",
        openapi_url="/v1/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    register_error_handlers(app)

    v1 = APIRouter(prefix="/v1")
    v1.include_router(health.router)
    v1.include_router(me.router)
    v1.include_router(organizations.router)
    v1.include_router(projects.router)
    v1.include_router(brands.router)
    v1.include_router(brand_brain.router)
    v1.include_router(campaigns.router)
    v1.include_router(composition.router)
    app.include_router(v1)
    return app


app = create_app()
