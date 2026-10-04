"""Tests that never touch the database: configuration, authentication, middleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workspace_api.config import AuthMode, ConfigError, Environment, Settings

URL = "postgresql+psycopg://user:s3cret@db.internal:5432/app"


def test_dev_auth_is_refused_in_production() -> None:
    with pytest.raises(ConfigError, match="refused when APP_ENV=production"):
        Settings(database_url=URL, environment=Environment.PRODUCTION, auth_mode=AuthMode.DEV)


def test_wildcard_cors_is_refused() -> None:
    with pytest.raises(ConfigError, match="explicit origins"):
        Settings(database_url=URL, cors_origins=("*",))


def test_non_postgres_url_is_refused() -> None:
    with pytest.raises(ConfigError, match="PostgreSQL"):
        Settings(database_url="sqlite:///x.db")


def test_settings_repr_redacts_password() -> None:
    text = repr(Settings(database_url=URL))
    assert "s3cret" not in text
    assert "user:***@db.internal" in text


def test_from_env_requires_database_url() -> None:
    with pytest.raises(ConfigError, match="DATABASE_URL is required"):
        Settings.from_env({})


def test_from_env_rejects_unknown_auth_mode() -> None:
    with pytest.raises(ConfigError, match="invalid configuration"):
        Settings.from_env({"DATABASE_URL": URL, "AUTH_MODE": "none"})


def test_from_env_parses_cors_list() -> None:
    settings = Settings.from_env({"DATABASE_URL": URL, "CORS_ORIGINS": "http://localhost:5173, http://127.0.0.1:5173"})
    assert settings.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")


# --------------------------------------------------------------------------- authentication


def test_missing_identity_headers_return_401_problem(offline_app: FastAPI) -> None:
    with TestClient(offline_app) as client:
        response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "urn:workspace:error:unauthenticated"
    assert body["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Dev-Tenant": "ACME", "X-Dev-User": "alice"},
        {"X-Dev-Tenant": "acme;drop", "X-Dev-User": "alice"},
        {"X-Dev-Tenant": "acme", "X-Dev-User": "aliceé"},
        {"X-Dev-Tenant": "acme", "X-Dev-User": "../../etc"},
    ],
)
def test_malformed_identity_headers_are_rejected(offline_app: FastAPI, headers: dict[str, str]) -> None:
    with TestClient(offline_app) as client:
        assert client.get("/api/v1/projects", headers=headers).status_code == 401


# --------------------------------------------------------------------------- middleware


def test_security_headers_and_request_id(offline_app: FastAPI) -> None:
    with TestClient(offline_app) as client:
        response = client.get("/healthz", headers={"X-Request-Id": "trace-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_unsafe_request_id_is_replaced(offline_app: FastAPI) -> None:
    with TestClient(offline_app) as client:
        response = client.get("/healthz", headers={"X-Request-Id": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


def test_oversized_body_with_content_length_is_rejected(offline_app: FastAPI) -> None:
    with TestClient(offline_app) as client:
        response = client.post("/api/v1/projects", content=b"x" * 5000, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["type"] == "urn:workspace:error:payload-too-large"


def test_oversized_chunked_body_is_rejected(offline_app: FastAPI) -> None:
    def chunks():  # type: ignore[no-untyped-def]
        for _ in range(10):
            yield b"x" * 1000

    with TestClient(offline_app) as client:
        response = client.post("/api/v1/projects", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_json_schema_endpoint_is_public_contract(offline_app: FastAPI) -> None:
    with TestClient(offline_app) as client:
        schema = client.get("/api/v1/schemas/application-spec").json()
    assert schema["title"] == "ApplicationSpec"


def test_openapi_documents_problem_responses(offline_app: FastAPI) -> None:
    spec = offline_app.openapi()
    put = spec["paths"]["/api/v1/projects/{project_id}/spec"]["put"]
    assert {"412", "422", "428"} <= set(put["responses"])
