from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}
USER = {"source": "user", "actor": "alice"}


def put(client: TestClient, pid: str, spec: dict[str, Any], revision: int = 1) -> None:
    response = client.put(f"/api/v1/projects/{pid}/spec", json={"spec": spec}, headers={"If-Match": f'"r{revision}"'})
    assert response.status_code == 200, response.text


def test_design_systems_are_listed_with_their_pinned_library(client: TestClient) -> None:
    items = client.get("/api/v1/design-systems").json()["items"]
    assert items == [
        {
            "id": "fluent2",
            "name": "Fluent 2 (React)",
            "version": "1.0.0",
            "framework": "react",
            "library_package": "@fluentui/react-components",
            "library_version": "9.74.9",
            "has_adapter": True,
        },
        {
            "id": "material3",
            "name": "Material 3 (Angular)",
            "version": "1.0.0",
            "framework": "angular",
            "library_package": "@angular/material",
            "library_version": "22.2.2",
            "has_adapter": False,
        },
    ]
    contract = client.get("/api/v1/design-systems/fluent2").json()
    assert contract["mappings"]["field:select"]["components"] == ["Field", "Select", "option"]
    assert contract["tokens"]["color.background.brand"] == "colorBrandBackground"
    material = client.get("/api/v1/design-systems/material3").json()
    assert material["mappings"]["field:select"]["components"][2] == "select[matNativeControl]"
    assert client.get("/api/v1/design-systems/acme").status_code == 404


def test_preview_derives_validates_and_renders_the_current_revision(
    client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    put(client, pid, example_spec)
    body = client.get(f"/api/v1/projects/{pid}/ui").json()
    assert body["spec_revision"] == 2
    assert body["design_system"] == {
        "id": "fluent2",
        "version": "1.0.0",
        "selected_by": "default",
        "note": "The spec selects no design system; Fluent 2 is the default for React.",
    }
    assert body["document"]["ir_version"] == "1"
    assert body["document"]["spec_revision"] == 2
    assert [s["id"] for s in body["document"]["screens"]] == ["adjustment-rules"]
    assert body["issues"] == []
    [rendered] = body["rendered"]
    title, table = rendered["root"]
    assert title == {
        "component": "Title2",
        "props": {"as": "h1"},
        "text": "Adjustment rules",
        "children": [],
        "ir_id": "adjustment-rules-title",
    }
    assert table["component"] == "Table"
    assert table["props"] == {"aria-label": "Adjustment"}

    # An older revision is previewed exactly as it was.
    first = client.get(f"/api/v1/projects/{pid}/ui", params={"revision": 1}).json()
    assert first["spec_revision"] == 1
    assert first["document"]["screens"] == []
    assert "assumption" in first["design_system"]["note"]
    assert client.get(f"/api/v1/projects/{pid}/ui", params={"revision": 9}).status_code == 404


def test_issues_are_reported_for_what_the_ir_cannot_express(
    client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    spec = copy.deepcopy(example_spec)
    spec["screens"][0]["components"].append({"id": "trend", "kind": "chart", "label": "Trend"})
    put(client, pid, spec)
    body = client.get(f"/api/v1/projects/{pid}/ui").json()
    assert [(i["code"], i["severity"]) for i in body["issues"]] == [("unsupported-component", "warning")]
    placeholder = body["rendered"][0]["root"][-1]
    assert placeholder["component"] == "div"
    assert placeholder["props"] == {"data-unsupported": "chart"}


def test_selected_design_system_must_exist_and_match_the_framework(
    client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]
) -> None:
    pid = make_project()["id"]
    spec = copy.deepcopy(example_spec)
    spec["design_system"] = {"id": {"value": "acme-ds", "status": "proposed", "provenance": USER}}
    put(client, pid, spec)
    response = client.get(f"/api/v1/projects/{pid}/ui")
    assert response.status_code == 422
    assert response.json()["type"] == "urn:workspace:error:design-system-unavailable"
    assert "acme-ds" in response.json()["detail"]

    spec["design_system"] = {
        "id": {"value": "fluent2", "status": "confirmed", "provenance": USER, "confirmed_by": "alice"}
    }
    put(client, pid, spec, revision=2)
    assert client.get(f"/api/v1/projects/{pid}/ui").json()["design_system"]["selected_by"] == "spec"

    spec["framework"]["framework"] = {"value": "angular", "status": "proposed", "provenance": USER}
    put(client, pid, spec, revision=3)
    mismatch = client.get(f"/api/v1/projects/{pid}/ui")
    assert mismatch.status_code == 422
    assert "but the app's framework is angular" in mismatch.json()["detail"]

    spec["design_system"] = {}
    put(client, pid, spec, revision=4)
    angular = client.get(f"/api/v1/projects/{pid}/ui").json()
    assert angular["design_system"]["id"] == "material3"
    assert angular["design_system"]["selected_by"] == "default"
    assert "Material 3 is the default for Angular" in angular["design_system"]["note"]
    assert "no in-browser preview yet" in angular["design_system"]["note"]
    assert angular["rendered"] == []
    assert [s["id"] for s in angular["document"]["screens"]] == ["adjustment-rules"]

    # Angular projects generate Angular + Material 3 code.
    code = client.get(f"/api/v1/projects/{pid}/code").json()
    assert code["generator"] == "codegen-angular@0.1.0"
    assert code["design_system"] == "material3@1.0.0"
    assert "src/app/screens/adjustment-rules-screen.ts" in [f["path"] for f in code["files"]]
    # The isolated runner only has the React toolchain; it says so instead of failing later.
    build = client.post(f"/api/v1/projects/{pid}/builds")
    assert build.status_code == 422
    assert build.json()["type"] == "urn:workspace:error:build-not-supported"


def test_preview_is_tenant_scoped(client: TestClient, make_project: Callable[..., dict[str, Any]]) -> None:
    pid = make_project()["id"]
    assert client.get(f"/api/v1/projects/{pid}/ui", headers=OTHER).status_code == 404
