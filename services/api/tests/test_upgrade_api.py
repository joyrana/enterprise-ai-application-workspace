from __future__ import annotations

import base64
import copy
import io
import json
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}
SCREEN = "src/screens/AdjustmentRulesScreen.tsx"
ZIP = {"Content-Type": "application/zip"}


@pytest.fixture
def pid(client: TestClient, make_project: Callable[..., dict[str, Any]], example_spec: dict[str, Any]) -> str:
    project_id = str(make_project("Finance ops")["id"])
    response = client.put(
        f"/api/v1/projects/{project_id}/spec", json={"spec": example_spec}, headers={"If-Match": '"r1"'}
    )
    assert response.status_code == 200, response.text
    return project_id


def unzip(data: bytes) -> tuple[str, dict[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        root = names[0].split("/", 1)[0]
        return root, {n.split("/", 1)[1]: zf.read(n) for n in names}


def rezip(root: str, files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path, data in files.items():
            zf.writestr(f"{root}/{path}", data)
    return buffer.getvalue()


def add_comment_field(client: TestClient, pid: str, spec: dict[str, Any]) -> None:
    changed = copy.deepcopy(spec)
    changed["entities"][0]["fields"].append({"name": "comment", "type": "text"})
    response = client.put(f"/api/v1/projects/{pid}/spec", json={"spec": changed}, headers={"If-Match": '"r2"'})
    assert response.status_code == 200, response.text


def test_edits_are_merged_with_regenerated_code(client: TestClient, pid: str, example_spec: dict[str, Any]) -> None:
    root, files = unzip(client.get(f"/api/v1/projects/{pid}/code.zip").content)
    files[SCREEN] = files[SCREEN] + b"\n// My helper, written by hand.\nexport const MY_CONSTANT = 42;\n"
    files["src/extra/notes.ts"] = b"export const notes = 'mine';\n"
    files["public/logo.png"] = b"\x89PNG\r\n\x1a\n\x00\xff"
    add_comment_field(client, pid, example_spec)

    response = client.post(f"/api/v1/projects/{pid}/code/upgrade", content=rezip(root, files), headers=ZIP)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["from_revision"], body["to_revision"], body["base_reproduced"], body["conflicts"]) == (2, 3, True, 0)
    status = {f["path"]: f["status"] for f in body["files"]}
    assert status[SCREEN] == "merged"
    assert status["src/extra/notes.ts"] == "user-file"
    assert status["public/logo.png"] == "user-file"
    assert status["package.json"] == "unchanged"
    assert status["workspace-manifest.json"] == "regenerated"

    new_root, merged = unzip(base64.b64decode(body["archive_base64"]))
    assert new_root == body["filename"].removesuffix(".zip")
    screen = merged[SCREEN].decode()
    assert "export const MY_CONSTANT = 42;" in screen  # the edit survived
    assert '{"Comment"}' in screen  # the regenerated change arrived
    assert "from spec r3" in screen
    assert merged["public/logo.png"] == b"\x89PNG\r\n\x1a\n\x00\xff"
    assert json.loads(merged["workspace-manifest.json"])["spec_revision"] == 3
    actions = [e["action"] for e in client.get(f"/api/v1/projects/{pid}/audit").json()["items"]]
    assert "code.upgraded" in actions


def test_overlapping_edits_are_marked_as_conflicts(client: TestClient, pid: str, example_spec: dict[str, Any]) -> None:
    root, files = unzip(client.get(f"/api/v1/projects/{pid}/code.zip").content)
    lines = files[SCREEN].decode().splitlines(keepends=True)
    lines[0] = "// I rewrote the provenance header.\n"  # the generator also changes this line (r2 -> r3)
    files[SCREEN] = "".join(lines).encode()
    add_comment_field(client, pid, example_spec)

    body = client.post(f"/api/v1/projects/{pid}/code/upgrade", content=rezip(root, files), headers=ZIP).json()
    entry = next(f for f in body["files"] if f["path"] == SCREEN)
    assert entry["status"] == "conflict"
    assert body["conflicts"] >= 1
    _, merged = unzip(base64.b64decode(body["archive_base64"]))
    screen = merged[SCREEN].decode()
    assert screen.startswith("<<<<<<< your edit\n// I rewrote the provenance header.\n=======\n")
    assert ">>>>>>> regenerated r3\n" in screen


def test_projects_from_another_generator_version_are_kept_side_by_side(
    client: TestClient, pid: str, example_spec: dict[str, Any]
) -> None:
    root, files = unzip(client.get(f"/api/v1/projects/{pid}/code.zip").content)
    manifest = json.loads(files["workspace-manifest.json"])
    manifest["generator"] = "codegen-react@0.0.1"
    files["workspace-manifest.json"] = json.dumps(manifest).encode()
    files[SCREEN] = files[SCREEN] + b"// edited\n"
    add_comment_field(client, pid, example_spec)

    body = client.post(f"/api/v1/projects/{pid}/code/upgrade", content=rezip(root, files), headers=ZIP).json()
    assert body["base_reproduced"] is False
    entry = next(f for f in body["files"] if f["path"] == SCREEN)
    assert entry["status"] == "side-by-side"
    _, merged = unzip(base64.b64decode(body["archive_base64"]))
    assert merged[SCREEN].endswith(b"// edited\n")
    assert '{"Comment"}' in merged[f"{SCREEN}.regenerated"].decode()


def test_unsafe_or_foreign_uploads_are_rejected_and_tenant_scoped(client: TestClient, pid: str) -> None:
    url = f"/api/v1/projects/{pid}/code/upgrade"
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as zf:
        zf.writestr("app/../../etc/passwd", "x")
    response = client.post(url, content=traversal.getvalue(), headers=ZIP)
    assert response.status_code == 422
    assert response.json()["type"] == "urn:workspace:error:upload-rejected"
    assert response.json()["errors"][0]["code"] == "unsafe-path"

    foreign = rezip("app", {"index.html": b"<html>"})
    response = client.post(url, content=foreign, headers=ZIP)
    assert response.status_code == 422
    assert "workspace-manifest.json" in response.json()["detail"]

    assert client.post(url, content=b"not a zip", headers=ZIP).status_code == 422
    root, files = unzip(client.get(f"/api/v1/projects/{pid}/code.zip").content)
    assert client.post(url, content=rezip(root, files), headers={**ZIP, **OTHER}).status_code == 404
