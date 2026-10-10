from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

ADMIN = {"X-Dev-Roles": "org-admin"}
USER = {"source": "user", "actor": "alice"}
ACME = {"id": "acme", "name": "Acme", "base": "fluent2", "brand_color": "#8A1538", "font_family": "Inter, sans-serif"}


def save(client: TestClient, items: list[dict[str, Any]], version: int, **headers: str) -> Any:
    return client.put(
        "/api/v1/org/design-systems",
        json={"themes": {"items": items}},
        headers={**ADMIN, "If-Match": f'"v{version}"', **headers},
    )


@pytest.fixture
def pid(client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]) -> str:
    project_id = str(make_project("Finance ops")["id"])
    spec = copy.deepcopy(example_spec)
    spec["design_system"] = {"id": {"value": "org:acme", "status": "proposed", "provenance": USER}}
    response = client.put(f"/api/v1/projects/{project_id}/spec", json={"spec": spec}, headers={"If-Match": '"r1"'})
    assert response.status_code == 200, response.text
    return project_id


def test_admins_manage_accessible_brand_themes(client: TestClient) -> None:
    assert client.get("/api/v1/org/design-systems").json() == {"version": 0, "themes": {"items": []}}
    denied = client.put("/api/v1/org/design-systems", json={"themes": {"items": [ACME]}}, headers={"If-Match": '"v0"'})
    assert denied.status_code == 403
    pale = save(client, [{**ACME, "brand_color": "#9ec5ff"}], 0)
    assert pale.status_code == 422
    assert "contrast" in pale.text
    saved = save(client, [ACME], 0)
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 1
    assert saved.json()["themes"]["items"][0]["brand_color"] == "#8a1538"
    assert save(client, [], 0).status_code == 412
    listing = client.get("/api/v1/design-systems").json()["items"]
    assert listing[0]["id"] == "org:acme"
    assert listing[0]["name"] == "Acme (organization theme on Fluent 2 (React))"


def test_projects_selecting_a_theme_generate_branded_code(client: TestClient, pid: str) -> None:
    missing = client.get(f"/api/v1/projects/{pid}/ui")
    assert missing.status_code == 422
    assert "not one of your organization's brand themes" in missing.json()["detail"]

    assert save(client, [ACME], 0).status_code == 200
    preview = client.get(f"/api/v1/projects/{pid}/ui").json()
    assert preview["design_system"]["id"] == "org:acme"
    assert preview["design_system"]["note"] == "Acme: organization brand theme on Fluent 2 (React)."
    assert preview["rendered"] != []

    code = client.get(f"/api/v1/projects/{pid}/code").json()
    assert code["design_system"] == "org:acme (fluent2@1.0.0)"
    theme = client.get(f"/api/v1/projects/{pid}/code/file", params={"path": "src/theme.ts"}).json()["content"]
    assert '  80: "#8a1538",' in theme
    assert '  fontFamilyBase: "Inter, sans-serif",' in theme

    # Policies can require the organization's theme.
    policy = {"rules": [{"id": "brand-only", "kind": "allowed-design-systems", "ids": ["org:acme"]}]}
    put = client.put("/api/v1/org/policies", json={"policy": policy}, headers={**ADMIN, "If-Match": '"v0"'})
    assert put.status_code == 200, put.text
    assert client.get(f"/api/v1/projects/{pid}/policy").json()["findings"] == []
