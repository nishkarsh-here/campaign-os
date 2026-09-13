"""Async engine and session factory.

One engine per process, created lazily so importing the app never opens a
connection — which is what keeps unit tests free of a database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        # A connection killed by a laptop sleep must not fail the next request.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)


def build_sessionmaker(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """An independent factory — used by tests to bind to the test database."""
    engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@lru_cache
def sessionmaker_for(database_url: str) -> async_sessionmaker[AsyncSession]:
    """A factory for the database *these* settings name.

    Background work outlives the request that started it, so it cannot borrow
    the request's session — it needs its own. It must not reach for the
    process-global factory either: that reads the cached global settings, which
    is the wrong database whenever the app was constructed with settings of its
    own. Cached per URL so a long-running app builds one engine, not one per
    request.
    """
    engine = create_async_engine(
        database_url, echo=False, pool_pre_ping=True, pool_size=2, max_overflow=3
    )
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def session_scope() -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on any error."""
    factory = get_sessionmaker()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
