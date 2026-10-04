from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

OTHER_TENANT = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}
MakeProject = Callable[..., dict[str, Any]]


def test_create_project_starts_with_empty_spec_at_revision_1(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "  Finance ops  ", "description": "Adjustments"})
    assert response.status_code == 201
    project = response.json()
    assert project["name"] == "Finance ops"
    assert project["current_revision"] == 1
    assert project["created_by"] == "alice"
    assert response.headers["location"] == f"/api/v1/projects/{project['id']}"

    spec = client.get(f"/api/v1/projects/{project['id']}/spec").json()
    assert spec["revision"] == 1
    assert spec["spec"]["metadata"] == {"name": "Finance ops", "description": "Adjustments", "tags": []}
    assert spec["spec"]["objective"]["status"] == "unknown"
    assert spec["spec"]["objective"]["value"] is None
    assert spec["summary"]["confirmed_facts"] == 0


def test_create_project_rejects_invalid_body_with_field_paths(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "   ", "unexpected": True})
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:workspace:error:validation-failed"
    assert {e["path"] for e in body["errors"]} == {"/name", "/unexpected"}


def test_idempotent_create_replays_the_same_project(client: TestClient) -> None:
    headers = {"Idempotency-Key": "create-finance-ops-1"}
    first = client.post("/api/v1/projects", json={"name": "Finance ops"}, headers=headers)
    second = client.post("/api/v1/projects", json={"name": "Finance ops"}, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/v1/projects").json()["items"]) == 1


def test_idempotency_key_reused_with_different_body_conflicts(client: TestClient) -> None:
    headers = {"Idempotency-Key": "create-finance-ops-2"}
    assert client.post("/api/v1/projects", json={"name": "A"}, headers=headers).status_code == 201
    response = client.post("/api/v1/projects", json={"name": "B"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["type"] == "urn:workspace:error:idempotency-key-reused"


def test_idempotency_keys_are_scoped_per_tenant(client: TestClient) -> None:
    headers = {"Idempotency-Key": "shared-key-123"}
    mine = client.post("/api/v1/projects", json={"name": "A"}, headers=headers)
    theirs = client.post("/api/v1/projects", json={"name": "A"}, headers={**headers, **OTHER_TENANT})
    assert (mine.status_code, theirs.status_code) == (201, 201)
    assert mine.json()["id"] != theirs.json()["id"]


def test_malformed_idempotency_key_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "A"}, headers={"Idempotency-Key": "short"})
    assert response.status_code == 400


def test_list_projects_paginates_newest_first(client: TestClient, make_project: MakeProject) -> None:
    ids = [make_project(f"Project {i}")["id"] for i in range(3)]
    page1 = client.get("/api/v1/projects", params={"limit": 2}).json()
    assert [p["id"] for p in page1["items"]] == [ids[2], ids[1]]
    assert page1["next_cursor"]
    page2 = client.get("/api/v1/projects", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
    assert [p["id"] for p in page2["items"]] == [ids[0]]
    assert page2["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["not-base64!!", "eyJmb28iOiAxfQ", "W10"])
def test_malformed_cursor_is_400(client: TestClient, cursor: str) -> None:
    assert client.get("/api/v1/projects", params={"cursor": cursor}).status_code == 400


@pytest.mark.parametrize("limit", [0, 101])
def test_limit_bounds(client: TestClient, limit: int) -> None:
    assert client.get("/api/v1/projects", params={"limit": limit}).status_code == 422


def test_unknown_project_is_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["type"] == "urn:workspace:error:not-found"


def test_tenants_cannot_see_each_others_projects(client: TestClient, make_project: MakeProject) -> None:
    project = make_project("Acme secret")
    pid = project["id"]
    for path in ("", "/spec", "/spec/revisions", "/spec/revisions/1", "/audit"):
        assert client.get(f"/api/v1/projects/{pid}{path}", headers=OTHER_TENANT).status_code == 404, path
    put = client.put(
        f"/api/v1/projects/{pid}/spec",
        json={"spec": {"metadata": {"name": "pwned"}}},
        headers={**OTHER_TENANT, "If-Match": '"r1"'},
    )
    assert put.status_code == 404
    assert client.get("/api/v1/projects", headers=OTHER_TENANT).json()["items"] == []
    # The owner's project is untouched.
    assert client.get(f"/api/v1/projects/{pid}").json()["name"] == "Acme secret"


def test_readiness_checks_database(client: TestClient) -> None:
    assert client.get("/readyz").json() == {"status": "ok"}
