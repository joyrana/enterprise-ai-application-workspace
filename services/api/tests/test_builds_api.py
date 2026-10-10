from __future__ import annotations

import copy
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from build_runner import BuildReport, SandboxLimits, StepResult, unpack
from workspace_api import builds
from workspace_api.db import Build

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


def fake_builder(seen: list[dict[str, Any]], status: str = "succeeded") -> builds.Builder:
    def build(archive: Path, output: Path, tools: dict[str, Any], image: str, limits: SandboxLimits) -> BuildReport:
        # The worker hands over the same archive users download; it passes the runner's verification.
        project = unpack(archive, output.parent / "verified", tools)
        with zipfile.ZipFile(archive) as zf:
            seen.append({"names": zf.namelist(), "image": image, "revision": project.spec_revision})
        return BuildReport(
            status=status,  # type: ignore[arg-type]
            image=image,
            steps=[StepResult("typecheck", 0, 10), StepResult("build", 0 if status == "succeeded" else 1, 20)],
            log_tail=["vite v6.4.3 building for production..."],
            artifacts={"index.html": "ab" * 32} if status == "succeeded" else {},
            reason=None if status == "succeeded" else "step 'build' failed",
            isolation=["--network none", "--read-only"],
        )

    return build


def test_build_lifecycle_request_claim_and_report(client: TestClient, app: FastAPI, pid: str) -> None:
    response = client.post(f"/api/v1/projects/{pid}/builds")
    assert response.status_code == 202, response.text
    queued = response.json()
    assert (queued["status"], queued["spec_revision"], queued["report"]) == ("queued", 2, None)
    assert queued["generator"].startswith("codegen-react@")

    # One active build per project.
    again = client.post(f"/api/v1/projects/{pid}/builds")
    assert again.status_code == 409
    assert again.json()["type"] == "urn:workspace:error:build-already-active"

    seen: list[dict[str, Any]] = []
    build_id = builds.process_one(app.state.db, "runner:test", builder=fake_builder(seen), worker="w1")
    assert str(build_id) == queued["id"]
    assert seen[0]["image"] == "runner:test"
    assert seen[0]["revision"] == 2
    assert any(name.endswith("/workspace-manifest.json") for name in seen[0]["names"])
    assert builds.process_one(app.state.db, "runner:test", builder=fake_builder(seen)) is None

    done = client.get(f"/api/v1/projects/{pid}/builds/{queued['id']}").json()
    assert done["status"] == "succeeded"
    assert done["report"]["steps"] == [
        {"name": "typecheck", "exit_code": 0, "duration_ms": 10},
        {"name": "build", "exit_code": 0, "duration_ms": 20},
    ]
    assert done["report"]["isolation"] == ["--network none", "--read-only"]
    assert done["finished_at"] is not None
    listing = client.get(f"/api/v1/projects/{pid}/builds").json()["items"]
    assert [b["id"] for b in listing] == [queued["id"]]
    actions = [e["action"] for e in client.get(f"/api/v1/projects/{pid}/audit").json()["items"]]
    assert "build.requested" in actions
    assert "build.finished" in actions

    # Finished builds no longer block a new one.
    assert client.post(f"/api/v1/projects/{pid}/builds").status_code == 202


def test_failed_build_and_worker_errors_are_recorded(client: TestClient, app: FastAPI, pid: str) -> None:
    first = client.post(f"/api/v1/projects/{pid}/builds").json()
    builds.process_one(app.state.db, "r", builder=fake_builder([], status="failed"))
    failed = client.get(f"/api/v1/projects/{pid}/builds/{first['id']}").json()
    assert failed["status"] == "failed"
    assert failed["report"]["reason"] == "step 'build' failed"

    second = client.post(f"/api/v1/projects/{pid}/builds").json()

    def broken(*_args: Any) -> BuildReport:
        raise OSError("docker: command not found")

    builds.process_one(app.state.db, "r", builder=broken)
    errored = client.get(f"/api/v1/projects/{pid}/builds/{second['id']}").json()
    assert errored["status"] == "runner_error"
    assert errored["report"]["reason"] == "worker error: OSError"


def test_stale_running_builds_are_recovered(client: TestClient, app: FastAPI, pid: str) -> None:
    build = client.post(f"/api/v1/projects/{pid}/builds").json()
    session = app.state.db.new_session()
    try:
        session.execute(
            update(Build)
            .where(Build.id == build["id"])
            .values(status="running", started_at=datetime.now(UTC) - timedelta(hours=1))
        )
        session.commit()
        assert builds.recover_stale(session, SandboxLimits(timeout_s=60)) == 1
    finally:
        session.close()
    recovered = client.get(f"/api/v1/projects/{pid}/builds/{build['id']}").json()
    assert recovered["status"] == "runner_error"
    assert recovered["report"]["reason"] == "the worker stopped responding"


def test_builds_are_refused_when_generation_is_blocked_and_tenant_scoped(
    client: TestClient, pid: str, example_spec: dict[str, Any]
) -> None:
    assert client.post(f"/api/v1/projects/{pid}/builds", headers=OTHER).status_code == 404
    assert client.get(f"/api/v1/projects/{pid}/builds", headers=OTHER).status_code == 404
    build = client.post(f"/api/v1/projects/{pid}/builds").json()
    assert client.get(f"/api/v1/projects/{pid}/builds/{build['id']}", headers=OTHER).status_code == 404

    spec = copy.deepcopy(example_spec)
    spec["screens"][0]["components"][0]["id"] = "title"  # duplicate node id: the UI IR has an error
    response = client.put(f"/api/v1/projects/{pid}/spec", json={"spec": spec}, headers={"If-Match": '"r2"'})
    assert response.status_code == 200
    blocked = client.post(f"/api/v1/projects/{pid}/builds", params={"revision": 3})
    assert blocked.status_code == 422
    assert blocked.json()["type"] == "urn:workspace:error:code-generation-blocked"
