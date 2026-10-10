from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from workspace_api.db import AuditEvent

pytestmark = pytest.mark.db

ADMIN = {"X-Dev-Roles": "org-admin"}
OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory", "X-Dev-Roles": "org-admin"}
RULES = [
    {"id": "angular-only", "kind": "allowed-frameworks", "frameworks": ["angular"], "severity": "warning"},
    {"id": "small-forms", "kind": "max-form-fields", "max": 20},
    {"id": "no-file-uploads", "kind": "forbidden-components", "constructs": ["field:file"]},
]


@pytest.fixture
def pid(client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]) -> str:
    project_id = str(make_project("Finance ops")["id"])
    response = client.put(
        f"/api/v1/projects/{project_id}/spec", json={"spec": example_spec}, headers={"If-Match": '"r1"'}
    )
    assert response.status_code == 200, response.text
    return project_id


def save(client: TestClient, rules: list[dict[str, Any]], version: int, **headers: str) -> Any:
    return client.put(
        "/api/v1/org/policies",
        json={"policy": {"rules": rules}},
        headers={**ADMIN, "If-Match": f'"v{version}"', **headers},
    )


def test_policies_start_empty_and_only_admins_change_them(client: TestClient) -> None:
    first = client.get("/api/v1/org/policies")
    assert first.status_code == 200
    assert first.headers["ETag"] == '"v0"'
    assert first.json() == {
        "version": 0,
        "policy": {"policy_version": "1", "rules": []},
        "updated_by": None,
        "updated_at": None,
    }
    denied = client.put("/api/v1/org/policies", json={"policy": {"rules": RULES}}, headers={"If-Match": '"v0"'})
    assert denied.status_code == 403
    assert client.put("/api/v1/org/policies", json={"policy": {"rules": RULES}}, headers=ADMIN).status_code == 428

    saved = save(client, RULES, 0)
    assert saved.status_code == 200, saved.text
    assert saved.headers["ETag"] == '"v1"'
    assert saved.json()["version"] == 1
    assert saved.json()["updated_by"] == "alice"
    assert [r["id"] for r in saved.json()["policy"]["rules"]] == ["angular-only", "small-forms", "no-file-uploads"]

    stale = save(client, [], 0)
    assert stale.status_code == 412
    assert save(client, [], 1).json()["version"] == 2

    invalid = save(client, [{"id": "x1", "kind": "run-script", "code": "rm -rf /"}], 2)
    assert invalid.status_code == 422


def test_findings_warn_or_block_generation_builds_and_upgrades(
    client: TestClient, pid: str, example_spec: dict[str, Any]
) -> None:
    assert save(client, RULES, 0).status_code == 200
    report = client.get(f"/api/v1/projects/{pid}/policy").json()
    assert report["policy_version"] == 1
    assert report["design_system"] == "fluent2"
    assert report["blocked"] is False
    assert [(f["rule_id"], f["severity"]) for f in report["findings"]] == [("angular-only", "warning")]
    assert client.get(f"/api/v1/projects/{pid}/code").status_code == 200  # warnings do not block

    spec = copy.deepcopy(example_spec)
    spec["entities"][1]["fields"].append({"name": "evidence", "type": "file"})
    spec["screens"], spec["navigation"] = [], []  # entity screens: the transaction form gets a file input
    assert (
        client.put(f"/api/v1/projects/{pid}/spec", json={"spec": spec}, headers={"If-Match": '"r2"'}).status_code == 200
    )
    report = client.get(f"/api/v1/projects/{pid}/policy").json()
    assert report["blocked"] is True
    assert "no-file-uploads" in [f["rule_id"] for f in report["findings"]]

    blocked = client.get(f"/api/v1/projects/{pid}/code")
    assert blocked.status_code == 422
    body = blocked.json()
    assert body["type"] == "urn:workspace:error:policy-blocked"
    assert [e["code"] for e in body["errors"]] == ["no-file-uploads"]
    assert client.get(f"/api/v1/projects/{pid}/code.zip").status_code == 422
    assert client.post(f"/api/v1/projects/{pid}/builds").status_code == 422
    # The previous revision is still compliant and still generates.
    assert client.get(f"/api/v1/projects/{pid}/code", params={"revision": 2}).status_code == 200

    # The impact preview reports policy findings before anything is saved.
    impact = client.post(f"/api/v1/projects/{pid}/impact", json=spec).json()
    assert impact["generation_blocked"] is True
    assert "no-file-uploads" in [f["rule_id"] for f in impact["policy_findings"]]


def test_policies_are_tenant_scoped_and_audited(client: TestClient, app: FastAPI, pid: str) -> None:
    assert save(client, [{"id": "small", "kind": "max-form-fields", "max": 1}], 0).status_code == 200
    session = app.state.db.new_session()
    try:
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "org.policies.updated")).one()
    finally:
        session.close()
    assert (event.tenant_id, event.actor, event.project_id) == ("acme", "alice", None)
    assert event.details["rules"] == ["small"]
    other = client.get("/api/v1/org/policies", headers=OTHER).json()
    assert other["version"] == 0
    assert client.get(f"/api/v1/projects/{pid}/policy", headers=OTHER).status_code == 404
    assert client.get(f"/api/v1/projects/{pid}/policy").json()["policy_version"] == 1
