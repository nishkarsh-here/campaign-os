"""Integration fixtures — real Postgres, mock providers.

Each test runs inside a transaction that is rolled back afterwards, so tests
share one migrated database without sharing state and without the cost of
re-migrating per test.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.providers.local.storage import LocalStorageProvider

TEST_DATABASE_URL = os.environ.setdefault(
    "TEST_DATABASE_URL", "postgresql+asyncpg://nishkarsh@localhost:5432/campaign_os_test"
)

#: Where the HTTP app stores and serves bytes in tests. Process-wide so a test
#: can seed an object the app will later serve, and nowhere near the
#: developer's own storage root.
_API_STORAGE_ROOT = tempfile.mkdtemp(prefix="campaign-os-api-storage-")


@pytest.fixture
def api_storage() -> LocalStorageProvider:
    """The same storage the `client` fixture's app is wired to."""
    return LocalStorageProvider(_API_STORAGE_ROOT)


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[object]:
    """Function-scoped, with `NullPool`.

    pytest-asyncio gives each test its own event loop, and an asyncpg
    connection is bound to the loop that created it. A session-scoped engine
    therefore hands the second test a connection from a closed loop
    ("This Connection is closed"). NullPool keeps no connection between tests,
    which costs a connect per test — a few milliseconds — and removes the
    whole class of cross-loop bugs.
    """
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    """A session bound to an outer transaction that is always rolled back.

    Commits inside the code under test become savepoints, so service code can
    call `commit()` for real while the test still leaves no trace.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
        async with factory() as db:
            yield db
        await transaction.rollback()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired to the app, with the request session replaced by
    the rolled-back test session."""
    from app.api.deps import (
        get_db,
        get_evaluation_runner,
        get_generation_runner,
        get_guardian_runner,
        get_storage_provider,
    )
    from app.config import Settings, get_settings
    from app.main import create_app

    settings = Settings(
        app_env="test",
        database_url=TEST_DATABASE_URL,
        database_url_sync=TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql"),
        auth_provider="dev_stub",
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: session
    # `SettingsDep` resolves `get_settings()`, the lru_cached global that reads
    # backend/.env — not `app.state.settings`. Without this override the
    # discovery service would point its checkpointer at the development
    # database. Identical objects in production; only tests need the override.
    app.dependency_overrides[get_settings] = lambda: settings

    # Background generation is not executed over HTTP in tests. The test
    # session lives in a transaction that is rolled back, so a background task
    # opening its own session would see none of the rows the request just
    # wrote — and would leave a live connection behind after the test ended.
    # The orchestration itself is covered directly in test_generation.py.
    async def _no_background(*args: object, **kwargs: object) -> None:
        return None

    # The app would otherwise read and write the developer's own storage root,
    # which makes byte-serving routes untestable and leaves files behind. The
    # `api_storage` fixture is the same directory, so a test can seed what a
    # route will later serve.
    app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(_API_STORAGE_ROOT)

    app.dependency_overrides[get_generation_runner] = lambda: _no_background
    app.dependency_overrides[get_evaluation_runner] = lambda: _no_background
    app.dependency_overrides[get_guardian_runner] = lambda: _no_background

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@dataclass(frozen=True)
class Workspace:
    """The seeded caller: the dev stub's identity, with one organization."""

    user: object
    org: object


@pytest_asyncio.fixture
async def workspace(session: AsyncSession) -> Workspace:
    """A user matching the dev stub's subject, with exactly one membership.

    The subject must match `DevStubAuthProvider`'s, because identity binds on
    the subject and never on the email (M1_SECURITY_AUDIT finding A-1).
    """
    from tests.integration.factories import make_membership, make_org, make_user

    user = await make_user(session, email="demo@campaign-os.local")
    user.auth_subject = "dev-stub:demo@campaign-os.local"
    org = await make_org(session)
    await make_membership(session, user, org)
    await session.flush()
    return Workspace(user=user, org=org)


@pytest.fixture(scope="session", autouse=True)
def checkpoint_tables() -> None:
    """Create LangGraph's checkpoint tables once, before any test transaction.

    `setup()` issues `CREATE INDEX CONCURRENTLY`, which waits for every open
    transaction on the database. Running it inside a test — whose `session`
    fixture holds one open for the whole test — blocks forever. Same reason the
    application creates them at startup rather than per request.
    """
    import asyncio

    from app.config import get_settings
    from app.services.campaigns import ensure_checkpoint_tables

    settings = get_settings()
    dsn = settings.database_url_sync.replace("/campaign_os", "/campaign_os_test")

    async def _setup() -> None:
        from app.config import Settings

        await ensure_checkpoint_tables(
            Settings(app_env="test", database_url_sync=dsn, database_url=TEST_DATABASE_URL)
        )

    asyncio.run(_setup())
