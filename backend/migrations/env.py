"""Alembic environment.

The database URL comes from `Settings`, never from `alembic.ini`, so migrations
cannot be pointed at the wrong database by editing a config file. Alembic runs
synchronously against `DATABASE_URL_SYNC` (psycopg); the application uses the
async DSN.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import models  # noqa: F401  -- import registers the tables on Base.metadata
from app.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().alembic_url)
target_metadata = Base.metadata

#: Tables LangGraph creates and owns (ADR-004). They are not in our metadata,
#: so autogenerate sees them as orphans and proposes dropping them — which
#: would destroy every in-flight campaign conversation. We neither model nor
#: migrate them; `AsyncPostgresSaver.setup()` does, at application startup.
FOREIGN_TABLES = frozenset(
    {"checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"}
)


def include_name(name: str | None, type_: str, _parent_names: dict[str, str | None]) -> bool:
    """Keep reflection away from tables this project does not own."""
    if type_ == "table":
        return name not in FOREIGN_TABLES
    return True


def include_object(
    obj: object, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """The hook autogenerate consults when comparing.

    `include_name` filters reflection; this filters the comparison, and both
    are needed — without it a future `alembic revision --autogenerate` emits
    `drop_table("checkpoints")` and takes every paused conversation with it.
    """
    if type_ == "table":
        return name not in FOREIGN_TABLES
    parent = getattr(obj, "table", None)
    return getattr(parent, "name", None) not in FOREIGN_TABLES


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_name=include_name,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
