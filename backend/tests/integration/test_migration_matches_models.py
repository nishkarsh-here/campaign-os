"""The migration and the ORM must describe the same database.

They are written by hand and drift silently: a column added to a model without
a migration works in tests that never touch a real database, then fails on
deploy. This compares the migrated schema against the declarative metadata.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from app.db import models  # noqa: F401  -- registers tables
from app.db.base import Base

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "organizations",
    "users",
    "memberships",
    "projects",
    # Milestone 2
    "brand_profiles",
    "brand_documents",
    "brand_assets",
    "brand_chunks",
    "brand_facts",
    # Milestone 3
    "campaigns",
    "campaign_runs",
    "campaign_messages",
    "campaign_specifications",
    "campaign_references",
    # Milestone 5
    "creative_direction_sets",
    "creative_specifications",
    "creative_approvals",
    "creative_revisions",
    # Milestone 6
    "canonical_prompts",
    "model_prompts",
    "generation_jobs",
    "generated_assets",
    # Milestone 7
    "creative_evaluations",
    "creative_selections",
    # Milestone 8
    "brand_guardian_results",
    "specification_revisions",
    # Milestone 9
    "layout_specs",
    "final_assets",
}


async def _table_names(engine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def _columns(engine, table_name: str) -> dict[str, object]:
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda c: inspect(c).get_columns(table_name))
    return {c["name"]: c["type"] for c in columns}


async def _column_names(engine, table_name: str) -> set[str]:
    """The inspection must happen *inside* the connection block: an Inspector
    outlives nothing, and using one after its connection closes raises
    ResourceClosedError."""
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda c: inspect(c).get_columns(table_name))
    return {c["name"] for c in columns}


class TestSchemaMatchesModels:
    async def test_migration_created_exactly_the_milestone_1_tables(self, engine) -> None:
        """No speculative tables: brands, campaigns and the rest arrive with
        the milestone that uses them."""
        actual = await _table_names(engine) - {"alembic_version"}
        checkpointer = {
            "checkpoints",
            "checkpoint_writes",
            "checkpoint_blobs",
            "checkpoint_migrations",
        }
        assert actual - checkpointer == EXPECTED_TABLES

    @pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
    async def test_columns_match_the_model(self, engine, table_name: str) -> None:
        in_db = await _column_names(engine, table_name)
        in_model = set(Base.metadata.tables[table_name].columns.keys())
        assert in_model == in_db, (
            f"{table_name}: model-only={in_model - in_db}, db-only={in_db - in_model}"
        )

    @pytest.mark.parametrize("table_name", sorted(EXPECTED_TABLES))
    async def test_timestamp_columns_are_timezone_aware(self, engine, table_name: str) -> None:
        """Names alone are not enough. `projects.deleted_at` was declared as a
        bare `mapped_column()` — naive `DateTime` in the ORM against
        `timestamptz` in the database — and a name-only comparison missed it
        until Alembic autogenerate surfaced it during Milestone 2."""
        for name, column_type in (await _columns(engine, table_name)).items():
            if name.endswith("_at"):
                assert getattr(column_type, "timezone", False) is True, (
                    f"{table_name}.{name} is not timezone-aware"
                )

    async def test_the_vector_index_survives_every_migration(self, engine) -> None:
        """Regression: `alembic autogenerate` proposed dropping the HNSW index
        while generating migration 003, because the ORM never declared it. It
        is declared now, and this asserts it is actually there — a retrieval
        index that quietly disappears looks like a performance mystery, not a
        migration bug."""
        from sqlalchemy import text

        async with engine.connect() as conn:
            rows = await conn.execute(
                text("select indexname from pg_indexes where tablename = 'brand_chunks'")
            )
            names = {r[0] for r in rows}
        assert "ix_brand_chunks_embedding_hnsw" in names

    async def test_required_extensions_are_installed(self, engine) -> None:
        from sqlalchemy import text

        async with engine.connect() as conn:
            rows = await conn.execute(text("select extname from pg_extension"))
            installed = {r[0] for r in rows}
        assert {"pgcrypto", "citext", "vector"} <= installed

    async def test_tenancy_columns_exist_on_root_tables(self, engine) -> None:
        """DATABASE_SCHEMA §Tenancy: these are the tables scope hangs off."""
        for table_name in ("projects", "memberships"):
            assert "organization_id" in await _column_names(engine, table_name)


class TestForeignTablesAreProtected:
    """LangGraph owns its checkpoint tables (ADR-004).

    Autogenerate sees tables absent from our metadata as orphans and proposes
    dropping them. `drop_table("checkpoints")` would delete every paused
    campaign conversation, so `migrations/env.py` excludes them explicitly.
    """

    def test_the_checkpoint_tables_are_excluded_from_autogenerate(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "alembic_env_probe", Path(__file__).resolve().parents[2] / "migrations" / "env.py"
        )
        assert spec and spec.loader
        # Reading the source is enough, and avoids executing migration context.
        source = (Path(__file__).resolve().parents[2] / "migrations" / "env.py").read_text()
        for table in (
            "checkpoints",
            "checkpoint_writes",
            "checkpoint_blobs",
            "checkpoint_migrations",
        ):
            assert f'"{table}"' in source, f"{table} is not excluded from autogenerate"
        assert "include_object" in source
        assert "include_name" in source
