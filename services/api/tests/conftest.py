from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from workspace_api.app import create_app
from workspace_api.config import Environment, Settings

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = API_ROOT.parents[1]
EXAMPLE_SPEC = REPO_ROOT / "packages" / "application-spec" / "examples" / "finance-operations.json"
PLACEHOLDER_URL = "postgresql+psycopg://test@localhost/unused"
HEADERS = {"X-Dev-Tenant": "acme", "X-Dev-User": "alice"}
OTHER_TENANT = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}


def _base_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail("REQUIRE_DB=1 but DATABASE_URL is not set: database tests must not be skipped in CI")
        pytest.skip("DATABASE_URL not set; skipping database tests")
    return url


def create_temp_database() -> str:
    base = _base_url()
    name = f"workspace_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return make_url(base).set(database=name).render_as_string(hide_password=False)


def drop_temp_database(url: str) -> None:
    name = make_url(url).database
    admin = create_engine(_base_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["configure_logging"] = False
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = create_temp_database()
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        drop_temp_database(url)


@pytest.fixture
def empty_database_url() -> Iterator[str]:
    """A brand-new, unmigrated database, dropped after the test."""
    url = create_temp_database()
    try:
        yield url
    finally:
        drop_temp_database(url)


@pytest.fixture
def make_alembic_config() -> Callable[[str], Config]:
    return alembic_config


@pytest.fixture
def app(database_url: str) -> Iterator[FastAPI]:
    application = create_app(
        Settings(database_url=database_url, environment=Environment.TEST, max_body_bytes=262_144),
        model_runtime=None,
    )
    yield application
    engine = application.state.db.engine
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE workflow_runs, audit_events, spec_revisions, projects RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, headers=HEADERS) as c:
        yield c


@pytest.fixture
def offline_app() -> FastAPI:
    """App whose database is never reached: for auth, config and middleware tests."""
    return create_app(
        Settings(database_url=PLACEHOLDER_URL, environment=Environment.TEST, max_body_bytes=4096), model_runtime=None
    )


@pytest.fixture
def example_spec() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE_SPEC.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def make_project(client: TestClient) -> Callable[..., dict[str, Any]]:
    def _make(name: str = "Finance ops", headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = client.post("/api/v1/projects", json={"name": name}, headers=headers)
        assert response.status_code == 201, response.text
        body: dict[str, Any] = response.json()
        return body

    return _make
