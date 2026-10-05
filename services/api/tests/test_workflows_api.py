"""Multi-step workflows over real HTTP and PostgreSQL, with a scripted model (tier 2, ADR-0010).

TestClient runs background tasks before returning, so each request below has
finished every step run it started by the time the response arrives.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from model_gateway import Capabilities, ErrorKind, FakeProvider, ModelError
from workspace_api.ai import ModelRuntime

pytestmark = pytest.mark.db

OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}

DISCOVERY: dict[str, Any] = {
    "is_application_request": True,
    "domain": "Finance operations",
    "objective": "Reduce manual effort for adjustments and approvals.",
    "personas": [{"name": "Operations analyst"}, {"name": "Finance approver"}],
    "requirements": [
        {"title": "Configure adjustment rules", "priority": "must", "persona_names": ["Operations analyst"]},
        {"title": "Approve risky transactions", "priority": "must", "persona_names": ["Finance approver"]},
    ],
    "open_questions": [],
    "assumptions": [],
}
CRITERIA: dict[str, Any] = {
    "criteria": [
        {"requirement_id": "configure-adjustment-rules", "given": "an analyst", "when": "saving", "then": "stored"},
        {"requirement_id": "approve-risky-transactions", "given": "a risky item", "when": "flagged", "then": "routed"},
    ]
}
NO_CONFLICTS: dict[str, Any] = {"conflicts": []}


@pytest.fixture
def ai(app: FastAPI) -> Callable[..., FakeProvider]:
    def _configure(*replies: Any) -> FakeProvider:
        provider = FakeProvider(list(replies))
        app.state.model_runtime = ModelRuntime(
            label=f"{provider.profile}:{provider.model_id}",
            profile=provider.profile,
            model_id=provider.model_id,
            capabilities=Capabilities(remote=False),
            factory=lambda: provider,
        )
        return provider

    return _configure


@pytest.fixture
def pid(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Finance ops"})
    assert response.status_code == 201
    return str(response.json()["id"])


def start(client: TestClient, pid: str, message: str = "Finance ops app", **headers: str) -> Any:
    return client.post(
        f"/api/v1/projects/{pid}/workflows",
        json={"definition_id": "requirements-pipeline", "message": message},
        headers=headers,
    )


def get(client: TestClient, pid: str, wid: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/projects/{pid}/workflows/{wid}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def run_of(client: TestClient, pid: str, wf: dict[str, Any], step: int) -> dict[str, Any]:
    run_id = wf["steps"][step]["run_ids"][-1]
    body: dict[str, Any] = client.get(f"/api/v1/projects/{pid}/runs/{run_id}").json()
    return body


def apply_all(client: TestClient, pid: str, run: dict[str, Any], revision: int, decision: str = "accept") -> Any:
    decisions = [{"proposal_id": p["proposal_id"], "decision": decision} for p in run["proposals"]]
    response = client.post(
        f"/api/v1/projects/{pid}/runs/{run['id']}/apply",
        json={"decisions": decisions},
        headers={"If-Match": f'"r{revision}"'},
    )
    assert response.status_code == 200, response.text
    return response.json()


def statuses(wf: dict[str, Any]) -> list[str]:
    return [s["status"] for s in wf["steps"]]


def actions(client: TestClient, pid: str) -> list[str]:
    return [e["action"] for e in reversed(client.get(f"/api/v1/projects/{pid}/audit?limit=100").json()["items"])]


def test_definitions_are_listed(client: TestClient) -> None:
    items = client.get("/api/v1/workflow-definitions").json()["items"]
    pipeline = next(d for d in items if d["id"] == "requirements-pipeline")
    assert [s["skill_id"] for s in pipeline["steps"]] == [
        "business-discovery",
        "acceptance-criteria",
        "requirements-conflict-detection",
    ]
    assert pipeline["max_attempts_per_step"] == 2


def test_pipeline_pauses_for_review_and_each_step_builds_on_the_applied_revision(
    client: TestClient, pid: str, ai: Callable[..., FakeProvider]
) -> None:
    provider = ai(DISCOVERY, CRITERIA, NO_CONFLICTS)
    created = start(client, pid)
    assert created.status_code == 202, created.text
    assert created.headers["location"].endswith(f"/workflows/{created.json()['id']}")
    wid = created.json()["id"]

    wf = get(client, pid, wid)
    assert wf["status"] == "awaiting_review"
    assert statuses(wf) == ["awaiting_review", "pending", "pending"]
    first = run_of(client, pid, wf, 0)
    assert first["workflow_id"] == wid
    assert first["workflow_step"] == 0
    assert first["routing"]["method"] == "explicit"
    assert len(provider.requests) == 1  # nothing else starts before the person decides
    assert client.get(f"/api/v1/projects/{pid}").json()["current_revision"] == 1

    apply_all(client, pid, first, revision=1)
    wf = get(client, pid, wid)
    assert wf["steps"][0]["applied_revision"] == 2
    assert statuses(wf) == ["completed", "awaiting_review", "pending"]
    second = run_of(client, pid, wf, 1)
    assert second["base_revision"] == 2  # built on what the person accepted
    assert second["skill_id"] == "acceptance-criteria"
    assert second["message"] == "Write acceptance criteria for the requirements."
    assert len(second["proposals"]) == 2

    apply_all(client, pid, second, revision=2)
    wf = get(client, pid, wid)
    # The conflict check found nothing, so it completed without a review and the workflow finished.
    assert wf["status"] == "completed"
    assert statuses(wf) == ["completed", "completed", "completed"]
    assert wf["steps"][2]["reason"]
    assert wf["finished_at"] is not None
    assert wf["active_run_id"] is None
    assert wf["can_resume"] is False
    assert len(provider.requests) == 3
    log = actions(client, pid)
    assert log.index("workflow.started") < log.index("workflow.completed")
    assert log.count("ai.run.started") == 3


def test_rejecting_all_discovery_proposals_skips_steps_that_need_requirements(
    client: TestClient, pid: str, ai: Callable[..., FakeProvider]
) -> None:
    provider = ai(DISCOVERY)
    wid = start(client, pid).json()["id"]
    first = run_of(client, pid, get(client, pid, wid), 0)
    apply_all(client, pid, first, revision=1, decision="reject")
    wf = get(client, pid, wid)
    assert wf["status"] == "completed"
    assert statuses(wf) == ["completed", "skipped", "skipped"]
    assert wf["steps"][0]["reason"] == "All proposals were rejected."
    assert wf["steps"][1]["reason"] == "Needs /functional_requirements in the specification."
    assert len(provider.requests) == 1
    assert actions(client, pid).count("workflow.step_skipped") == 2


def test_failed_step_is_resumed_once_then_refused(
    client: TestClient, pid: str, ai: Callable[..., FakeProvider]
) -> None:
    ai(ModelError(ErrorKind.UNAVAILABLE, "HTTP 503"))
    wid = start(client, pid).json()["id"]
    wf = get(client, pid, wid)
    assert wf["status"] == "failed"
    assert wf["steps"][0]["status"] == "failed"
    assert wf["steps"][0]["reason"]
    assert wf["can_resume"] is True

    ai(ModelError(ErrorKind.UNAVAILABLE, "HTTP 503"))
    resumed = client.post(f"/api/v1/projects/{pid}/workflows/{wid}/resume")
    assert resumed.status_code == 200, resumed.text
    wf = get(client, pid, wid)
    assert wf["steps"][0]["attempts"] == 2
    assert len(wf["steps"][0]["run_ids"]) == 2
    assert wf["status"] == "failed"
    assert wf["can_resume"] is False

    refused = client.post(f"/api/v1/projects/{pid}/workflows/{wid}/resume")
    assert refused.status_code == 409
    assert refused.json()["type"] == "urn:workspace:error:workflow-state-conflict"
    assert "maximum" in refused.json()["detail"]


def test_interrupted_step_is_recovered_and_resumed(
    app: FastAPI, client: TestClient, pid: str, ai: Callable[..., FakeProvider]
) -> None:
    """Simulate a process that stopped mid-step: the run never finished and nothing updated the checkpoint."""
    ai(DISCOVERY)
    wid = start(client, pid).json()["id"]
    run_id = get(client, pid, wid)["steps"][0]["run_ids"][0]
    long_ago = datetime.now(UTC) - timedelta(hours=2)
    with app.state.db.engine.begin() as conn:
        conn.execute(
            text("UPDATE workflow_runs SET status='running', result=NULL, started_at=:t WHERE id=:id"),
            {"t": long_ago, "id": run_id},
        )
        conn.execute(
            text(
                "UPDATE workflows SET status='running', "
                "state = jsonb_set(jsonb_set(state, '{steps,0,status}', '\"running\"'), '{status}', '\"running\"') "
                "WHERE id=:id"
            ),
            {"id": wid},
        )

    wf = get(client, pid, wid)  # reading reconciles: the stale run is expired and the step fails
    assert wf["status"] == "failed"
    assert wf["steps"][0]["status"] == "failed"
    assert wf["can_resume"] is True
    assert client.get(f"/api/v1/projects/{pid}/runs/{run_id}").json()["error"]["kind"] == "interrupted"

    ai(DISCOVERY)
    client.post(f"/api/v1/projects/{pid}/workflows/{wid}/resume")
    wf = get(client, pid, wid)
    assert wf["status"] == "awaiting_review"
    assert wf["steps"][0]["attempts"] == 2
    assert "workflow.resumed" in actions(client, pid)


def test_cancel_stops_further_steps(client: TestClient, pid: str, ai: Callable[..., FakeProvider]) -> None:
    provider = ai(DISCOVERY)
    wid = start(client, pid).json()["id"]
    cancelled = client.post(f"/api/v1/projects/{pid}/workflows/{wid}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # The step's proposals can still be applied as an ordinary run, but nothing further starts.
    apply_all(client, pid, run_of(client, pid, get(client, pid, wid), 0), revision=1)
    wf = get(client, pid, wid)
    assert wf["status"] == "cancelled"
    assert statuses(wf)[1:] == ["pending", "pending"]
    assert len(provider.requests) == 1
    again = client.post(f"/api/v1/projects/{pid}/workflows/{wid}/cancel")
    assert again.status_code == 409
    assert client.post(f"/api/v1/projects/{pid}/workflows/{wid}/resume").status_code == 409


def test_start_is_idempotent(client: TestClient, pid: str, ai: Callable[..., FakeProvider]) -> None:
    provider = ai(DISCOVERY)
    first = start(client, pid, **{"Idempotency-Key": "pipeline-attempt-1"})
    second = start(client, pid, **{"Idempotency-Key": "pipeline-attempt-1"})
    assert first.status_code == 202
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(provider.requests) == 1
    conflict = start(client, pid, "Different text", **{"Idempotency-Key": "pipeline-attempt-1"})
    assert conflict.status_code == 409


def test_start_requires_a_model_and_a_known_definition(client: TestClient, pid: str) -> None:
    assert start(client, pid).status_code == 503
    assert client.get(f"/api/v1/projects/{pid}/workflows").json()["items"] == []
    unknown = client.post(f"/api/v1/projects/{pid}/workflows", json={"definition_id": "nope", "message": "x"})
    assert unknown.status_code == 404


def test_workflows_are_tenant_scoped(client: TestClient, pid: str, ai: Callable[..., FakeProvider]) -> None:
    ai(DISCOVERY)
    wid = start(client, pid).json()["id"]
    assert client.get(f"/api/v1/projects/{pid}/workflows/{wid}", headers=OTHER).status_code == 404
    assert client.post(f"/api/v1/projects/{pid}/workflows/{wid}/cancel", headers=OTHER).status_code == 404
    assert client.get(f"/api/v1/projects/{pid}/workflows", headers=OTHER).status_code == 404
    listed = client.get(f"/api/v1/projects/{pid}/workflows").json()["items"]
    assert [w["id"] for w in listed] == [wid]
