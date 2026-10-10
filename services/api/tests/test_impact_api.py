from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}


@pytest.fixture
def pid(client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]) -> str:
    project_id = str(make_project("Finance ops")["id"])
    response = client.put(
        f"/api/v1/projects/{project_id}/spec", json={"spec": example_spec}, headers={"If-Match": '"r1"'}
    )
    assert response.status_code == 200, response.text
    return project_id


def test_impact_lists_entities_screens_and_files_without_saving(
    client: TestClient, pid: str, example_spec: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(example_spec)
    candidate["entities"][0]["fields"].append({"name": "comment", "type": "text"})
    response = client.post(f"/api/v1/projects/{pid}/impact", json=candidate)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_revision"] == 2
    assert body["spec_valid"] is True
    assert body["generation_blocked"] is False
    assert body["entities"]["changed"] == ["Adjustment"]
    assert body["entities"]["added"] == []
    assert body["screens"]["changed"] == ["Adjustment rules"]
    files = {f["path"]: f for f in body["files"]}
    screen = files["src/screens/AdjustmentRulesScreen.tsx"]
    assert screen["status"] == "modified"
    assert screen["additions"] >= 2
    # Same revision on both sides: untouched files do not show up because of header changes.
    assert "package.json" not in files
    assert "src/App.tsx" not in files
    assert client.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 2


def test_impact_reports_invalid_specs_and_generation_blockers(
    client: TestClient, pid: str, example_spec: dict[str, Any]
) -> None:
    invalid = copy.deepcopy(example_spec)
    invalid["screens"][0]["persona_ids"] = ["nobody"]
    body = client.post(f"/api/v1/projects/{pid}/impact", json=invalid).json()
    assert body["spec_valid"] is False
    assert "dangling-reference" in [i["code"] for i in body["spec_issues"]]
    assert body["files"] == []
    assert body["note"] is not None

    blocked = copy.deepcopy(example_spec)
    blocked["screens"][0]["components"][0]["id"] = "title"  # collides with the derived heading id
    body = client.post(f"/api/v1/projects/{pid}/impact", json=blocked).json()
    assert body["spec_valid"] is True
    assert body["generation_blocked"] is True
    assert [i["code"] for i in body["ui_issues"]] == ["id-duplicate"]


def test_impact_is_tenant_scoped(client: TestClient, pid: str, example_spec: dict[str, Any]) -> None:
    assert client.post(f"/api/v1/projects/{pid}/impact", json=example_spec, headers=OTHER).status_code == 404
