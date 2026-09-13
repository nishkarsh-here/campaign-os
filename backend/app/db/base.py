"""Declarative base and shared column conventions.

Mirrors `docs/DATABASE_SCHEMA.md`. Every deviation from that document is a bug
in one of the two — they are kept in step by an integration test that compares
the ORM metadata against the migrated database.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Deterministic constraint names, so Alembic autogenerate produces stable
#: migrations instead of database-assigned names that differ per environment.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    """UUID primary keys: no sequential ids in URLs (DATABASE_SCHEMA §Conventions)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class Entity(UUIDPrimaryKey, Base):
    """A table addressed by a UUID primary key.

    Exists so repositories can be bound to `Entity` rather than `Base`: a
    repository does `where(model.id == ...)`, and only this bound makes that
    statically true instead of an unchecked attribute access.
    """

    __abstract__ = True


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampsWithUpdate(Timestamps):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
