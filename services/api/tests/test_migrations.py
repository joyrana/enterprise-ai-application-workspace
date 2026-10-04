from __future__ import annotations

from collections.abc import Callable

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from workspace_api.db import Base

pytestmark = pytest.mark.db

TABLES = {"projects", "spec_revisions", "audit_events"}


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migrations_upgrade_downgrade_and_match_models(
    empty_database_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    cfg = make_alembic_config(empty_database_url)

    command.upgrade(cfg, "head")
    assert TABLES <= _tables(empty_database_url)

    # The ORM models and the migration history must describe the same schema.
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], diff

    command.downgrade(cfg, "base")
    assert not TABLES & _tables(empty_database_url)

    command.upgrade(cfg, "head")
    assert TABLES <= _tables(empty_database_url)
