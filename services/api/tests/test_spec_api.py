from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

MakeProject = Callable[..., dict[str, Any]]


def _put(client: TestClient, pid: str, spec: dict[str, Any], etag: str | None, summary: str | None = None) -> Any:
    headers = {"If-Match": etag} if etag is not None else {}
    body: dict[str, Any] = {"spec": spec}
    if summary:
        body["change_summary"] = summary
    return client.put(f"/api/v1/projects/{pid}/spec", json=body, headers=headers)


def test_get_spec_returns_etag(client: TestClient, make_project: MakeProject) -> None:
    pid = make_project()["id"]
    response = client.get(f"/api/v1/projects/{pid}/spec")
    assert response.headers["etag"] == '"r1"'


def test_save_requires_if_match(client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]) -> None:
    pid = make_project()["id"]
    response = _put(client, pid, example_spec, None)
    assert response.status_code == 428
    assert response.json()["type"] == "urn:workspace:error:precondition-required"


def test_save_creates_new_revision_and_syncs_project(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project("Placeholder")["id"]
    response = _put(client, pid, example_spec, '"r1"', "Captured discovery results")
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"r2"'
    assert response.headers["x-revision-created"] == "true"
    body = response.json()
    assert body["revision"] == 2
    assert body["change_summary"] == "Captured discovery results"
    assert body["content_hash"].startswith("sha256:")
    # Server-stamped artifact revisions.
    assert body["spec"]["personas"][0]["revision"] == {"created_in": 2, "updated_in": 2}
    assert body["spec"]["metadata"]["name"] == "Finance Operations Adjustments"
    # Warnings are returned but do not block saving.
    assert {i["code"] for i in body["issues"]} == {"requirement-without-acceptance-criteria"}

    project = client.get(f"/api/v1/projects/{pid}").json()
    assert project["name"] == "Finance Operations Adjustments"
    assert project["current_revision"] == 2


def test_stale_if_match_is_rejected_with_current_revision(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    assert _put(client, pid, example_spec, '"r1"').status_code == 200
    changed = copy.deepcopy(example_spec)
    changed["metadata"]["name"] = "Someone else's edit"
    response = _put(client, pid, changed, '"r1"')
    assert response.status_code == 412
    body = response.json()
    assert body["type"] == "urn:workspace:error:revision-conflict"
    assert body["extensions"]["current_revision"] == 2
    assert client.get(f"/api/v1/projects/{pid}").json()["name"] == "Finance Operations Adjustments"


@pytest.mark.parametrize("value", ["r1", '"1"', '"r0"', '"r1", "r2"', "*"])
def test_malformed_if_match_is_rejected(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any], value: str
) -> None:
    pid = make_project()["id"]
    assert _put(client, pid, example_spec, value).status_code == 412


def test_unchanged_save_does_not_create_a_revision(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    first = _put(client, pid, example_spec, '"r1"').json()
    # Resubmitting the stored document (including server stamps) is a no-op.
    again = _put(client, pid, first["spec"], '"r2"')
    assert again.status_code == 200
    assert again.headers["x-revision-created"] == "false"
    assert again.json()["revision"] == 2
    assert client.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 2


def test_only_changed_elements_get_new_revision_stamps(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    v2 = _put(client, pid, example_spec, '"r1"').json()["spec"]
    v2["personas"][1]["name"] = "Senior finance approver"
    v3 = _put(client, pid, v2, '"r2"').json()["spec"]
    by_id = {p["id"]: p["revision"] for p in v3["personas"]}
    assert by_id["approver"] == {"created_in": 2, "updated_in": 3}
    assert by_id["ops-analyst"] == {"created_in": 2, "updated_in": 2}


def test_dangling_references_are_rejected_with_paths(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    example_spec["acceptance_criteria"][0]["requirement_id"] = "nope"
    response = _put(client, pid, example_spec, '"r1"')
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:workspace:error:spec-invalid"
    assert body["errors"] == [
        {
            "path": "/acceptance_criteria/0/requirement_id",
            "message": "references unknown functional requirement 'nope'",
            "code": "dangling-reference",
        }
    ]
    assert client.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 1


def test_structurally_invalid_spec_is_rejected_with_paths(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    example_spec["personas"][0]["id"] = "Not Valid"
    example_spec["objective"] = {"value": "x", "status": "confirmed", "provenance": {"source": "user"}}
    response = _put(client, pid, example_spec, '"r1"')
    assert response.status_code == 422
    paths = {e["path"] for e in response.json()["errors"]}
    assert "/spec/personas/0/id" in paths
    assert any(p.startswith("/spec/objective") for p in paths)


def test_unsupported_schema_version_is_rejected(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    example_spec["schema_version"] = "2.0.0"
    assert _put(client, pid, example_spec, '"r1"').status_code == 422


def test_validate_endpoint_does_not_persist(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    example_spec["navigation"][0]["screen_id"] = "missing"
    result = client.post(f"/api/v1/projects/{pid}/spec/validate", json=example_spec).json()
    assert result["valid"] is False
    assert [i["path"] for i in result["issues"] if i["severity"] == "error"] == ["/navigation/0/screen_id"]
    assert client.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 1


def test_revision_history_is_preserved_and_paginated(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    spec = _put(client, pid, example_spec, '"r1"').json()["spec"]
    spec["metadata"]["name"] = "Renamed"
    _put(client, pid, spec, '"r2"', "Rename")

    page = client.get(f"/api/v1/projects/{pid}/spec/revisions", params={"limit": 2}).json()
    assert [r["revision"] for r in page["items"]] == [3, 2]
    rest = client.get(f"/api/v1/projects/{pid}/spec/revisions", params={"limit": 2, "cursor": page["next_cursor"]})
    assert [r["revision"] for r in rest.json()["items"]] == [1]

    original = client.get(f"/api/v1/projects/{pid}/spec/revisions/1").json()
    assert original["spec"]["metadata"]["name"] == "Finance ops"
    assert client.get(f"/api/v1/projects/{pid}/spec/revisions/99").status_code == 404


def test_audit_trail_records_changes(
    client: TestClient, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    _put(client, pid, example_spec, '"r1"', "Discovery")
    events = client.get(f"/api/v1/projects/{pid}/audit").json()["items"]
    assert [e["action"] for e in events] == ["spec.revised", "project.created"]
    assert events[0]["actor"] == "alice"
    assert events[0]["details"]["revision"] == 2
    assert events[0]["details"]["change_summary"] == "Discovery"


def test_revisions_are_immutable_in_the_database(app: FastAPI, client: TestClient, make_project: MakeProject) -> None:
    make_project()
    with pytest.raises(DBAPIError, match="immutable"), app.state.db.engine.begin() as conn:
        conn.execute(text("UPDATE spec_revisions SET change_summary = 'tampered'"))


def test_concurrent_saves_from_same_revision_cannot_both_win(
    app: FastAPI, make_project: MakeProject, example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    statuses: list[int] = []
    barrier = threading.Barrier(2)

    def save(name: str) -> None:
        spec = copy.deepcopy(example_spec)
        spec["metadata"]["name"] = name
        with TestClient(app, headers={"X-Dev-Tenant": "acme", "X-Dev-User": name}) as c:
            barrier.wait()
            statuses.append(_put(c, pid, spec, '"r1"').status_code)

    threads = [threading.Thread(target=save, args=(n,)) for n in ("writer-a", "writer-b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [200, 412]
    with TestClient(app, headers={"X-Dev-Tenant": "acme", "X-Dev-User": "alice"}) as c:
        assert c.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 2
