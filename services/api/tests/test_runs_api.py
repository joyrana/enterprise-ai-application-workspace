from __future__ import annotations

import copy
import uuid
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

HEADERS = {"X-Dev-Tenant": "acme", "X-Dev-User": "alice"}
OTHER = {"X-Dev-Tenant": "globex", "X-Dev-User": "mallory"}

ANSWER: dict[str, Any] = {
    "is_application_request": True,
    "domain": "Finance operations",
    "objective": "Reduce manual effort for adjustments and approvals.",
    "personas": [{"name": "Operations analyst"}, {"name": "Finance approver"}],
    "requirements": [
        {"title": "Configure adjustment rules", "priority": "must", "persona_names": ["Operations analyst"]},
        {"title": "Approve risky transactions", "priority": "must", "persona_names": ["Finance approver"]},
    ],
    "open_questions": [{"question": "What risk score requires approval?", "blocking": True}],
    "assumptions": [],
}


def runtime(provider: FakeProvider, *, remote: bool = False) -> ModelRuntime:
    return ModelRuntime(
        label=f"{provider.profile}:{provider.model_id}",
        profile=provider.profile,
        model_id=provider.model_id,
        capabilities=Capabilities(remote=remote),
        factory=lambda: provider,
    )


@pytest.fixture
def ai(app: FastAPI) -> Callable[..., FakeProvider]:
    """Attach a FakeProvider with scripted replies to the app under test."""

    def _configure(*replies: Any, remote: bool = False) -> FakeProvider:
        provider = FakeProvider(list(replies))
        app.state.model_runtime = runtime(provider, remote=remote)
        return provider

    return _configure


@pytest.fixture
def project(client: TestClient) -> dict[str, Any]:
    response = client.post("/api/v1/projects", json={"name": "Finance ops"})
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def start(
    client: TestClient, pid: str, message: str = "Finance ops app", skill_id: str | None = None, **headers: str
) -> Any:
    body: dict[str, Any] = {"message": message}
    if skill_id is not None:
        body["skill_id"] = skill_id
    return client.post(f"/api/v1/projects/{pid}/runs", json=body, headers=headers)


def decide(run: dict[str, Any], decision: str = "accept") -> list[dict[str, str]]:
    return [{"proposal_id": p["proposal_id"], "decision": decision} for p in run["proposals"]]


# --------------------------------------------------------------------------- status and preconditions


def test_ai_status_reports_unconfigured(client: TestClient) -> None:
    assert client.get("/api/v1/ai/status").json() == {
        "configured": False,
        "model": None,
        "profile": None,
        "remote": None,
        "structured_mode": None,
    }


def test_ai_status_reports_configured_model(client: TestClient, ai: Callable[..., FakeProvider]) -> None:
    ai()
    status = client.get("/api/v1/ai/status").json()
    assert status["configured"] is True
    assert status["model"] == "fake:fake-model"
    assert status["remote"] is False


def test_starting_without_a_model_is_503_and_creates_nothing(client: TestClient, project: dict[str, Any]) -> None:
    response = start(client, project["id"])
    assert response.status_code == 503
    assert response.json()["type"] == "urn:workspace:error:model-not-configured"
    assert client.get(f"/api/v1/projects/{project['id']}/runs").json()["items"] == []


def test_remote_model_is_refused_for_confidential_projects(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider], example_spec: dict[str, Any]
) -> None:
    spec = copy.deepcopy(example_spec)
    spec["security"]["classification"] = {
        "value": "confidential",
        "status": "confirmed",
        "provenance": {"source": "user"},
        "confirmed_by": "alice",
    }
    put = client.put(f"/api/v1/projects/{project['id']}/spec", json={"spec": spec}, headers={"If-Match": '"r1"'})
    assert put.status_code == 200
    provider = ai(ANSWER, remote=True)
    response = start(client, project["id"])
    assert response.status_code == 403
    assert response.json()["type"] == "urn:workspace:error:model-policy-denied"
    assert provider.requests == []  # nothing was sent to the model


def test_message_is_validated(client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]) -> None:
    ai(ANSWER)
    assert start(client, project["id"], message="   ").status_code == 422
    assert start(client, project["id"], message="x" * 8001).status_code == 422


# --------------------------------------------------------------------------- run lifecycle


def test_discovery_run_produces_proposals_without_changing_the_spec(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    provider = ai(ANSWER)
    response = start(client, project["id"], message="Configure adjustments and approve risky transactions")
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert response.headers["location"].endswith(f"/runs/{run_id}")

    # TestClient runs background tasks before returning, so the run has finished.
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["message"] == "Configure adjustments and approve risky transactions"
    assert run["base_revision"] == 1
    assert len(run["proposals"]) == 7
    assert run["model"]["model_id"] == "fake-model"
    assert run["model"]["prompt_version"] == "business-discovery@1"
    assert run["model"]["usage"]["total_tokens"] == 150
    assert run["error"] is None
    # The user's text reached the model as delimited data.
    assert "<user_description>" in provider.requests[0][1].content
    # Proposals are not applied automatically.
    assert client.get(f"/api/v1/projects/{project['id']}").json()["current_revision"] == 1


def test_runs_are_listed_newest_first_for_resume(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER, ANSWER)
    first = start(client, project["id"]).json()["id"]
    second = start(client, project["id"]).json()["id"]
    items = client.get(f"/api/v1/projects/{project['id']}/runs").json()["items"]
    assert [r["id"] for r in items] == [second, first]


def test_idempotent_start_replays_the_same_run(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    provider = ai(ANSWER)
    headers = {"Idempotency-Key": "discovery-attempt-1"}
    first = start(client, project["id"], **headers)
    second = start(client, project["id"], **headers)
    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(provider.requests) == 1


def test_model_failure_is_recorded_with_classified_error(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ModelError(ErrorKind.RATE_LIMITED, "HTTP 429 from provider"))
    run_id = start(client, project["id"]).json()["id"]
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error"] == {
        "kind": "rate_limited",
        "message": "The model provider is rate limiting requests. Try again shortly.",
    }
    assert run["proposals"] == []


def test_schema_failure_after_repair_is_recorded(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai("not json at all", "<think>still</think> nope")
    run_id = start(client, project["id"]).json()["id"]
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error"]["kind"] == "schema_failure"
    assert run["model"]["calls"] == 2


def test_not_an_application_request(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai({"is_application_request": False, "not_applicable_reason": "That is a weather question."})
    run_id = start(client, project["id"], message="Will it rain in Pune?").json()["id"]
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["proposals"] == []
    assert run["not_applicable_reason"] == "That is a weather question."


def test_active_run_limit_per_tenant(
    app: FastAPI, client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER)
    engine = app.state.db.engine
    with engine.begin() as conn:
        for _ in range(3):
            conn.execute(
                text(
                    "INSERT INTO workflow_runs (id, tenant_id, project_id, skill_id, skill_version, status, input, "
                    "base_revision, created_by) VALUES (:id, 'acme', :pid, 'business-discovery', '0.1.0', 'running', "
                    "'{\"description\": \"x\"}', 1, 'alice')"
                ),
                {"id": str(uuid.uuid4()), "pid": project["id"]},
            )
    response = start(client, project["id"])
    assert response.status_code == 429
    assert response.json()["type"] == "urn:workspace:error:too-many-active-runs"


def test_interrupted_runs_are_marked_failed(app: FastAPI, client: TestClient, project: dict[str, Any]) -> None:
    run_id = str(uuid.uuid4())
    old = datetime.now(UTC) - timedelta(hours=1)
    with app.state.db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflow_runs (id, tenant_id, project_id, skill_id, skill_version, status, input, "
                "base_revision, created_by, created_at, started_at) VALUES (:id, 'acme', :pid, 'business-discovery', "
                "'0.1.0', 'running', '{\"description\": \"x\"}', 1, 'alice', :old, :old)"
            ),
            {"id": run_id, "pid": project["id"], "old": old},
        )
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error"]["kind"] == "interrupted"


def test_runs_are_tenant_scoped(client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]) -> None:
    ai(ANSWER)
    run_id = start(client, project["id"]).json()["id"]
    base = f"/api/v1/projects/{project['id']}/runs"
    assert client.get(f"{base}/{run_id}", headers=OTHER).status_code == 404
    assert client.get(base, headers=OTHER).status_code == 404
    assert start(client, project["id"], **OTHER).status_code == 404
    apply = client.post(
        f"{base}/{run_id}/apply",
        json={"decisions": [{"proposal_id": "p-objective", "decision": "accept"}]},
        headers={**OTHER, "If-Match": '"r1"'},
    )
    assert apply.status_code == 404


# --------------------------------------------------------------------------- applying decisions


def test_apply_creates_one_revision_with_model_provenance(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER)
    pid = project["id"]
    run = start(client, pid).json()
    run = client.get(f"/api/v1/projects/{pid}/runs/{run['id']}").json()
    decisions = decide(run, "accept")
    objective = next(d for d in decisions if d["proposal_id"] == "p-objective")
    objective["decision"] = "confirm"
    question = next(p for p in run["proposals"] if p["op"] == "add_open_question")
    next(d for d in decisions if d["proposal_id"] == question["proposal_id"])["decision"] = "reject"

    response = client.post(
        f"/api/v1/projects/{pid}/runs/{run['id']}/apply",
        json={"decisions": decisions},
        headers={"If-Match": '"r1"'},
    )
    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"r2"'
    body = response.json()
    assert body["revision_created"] is True
    assert body["run"]["applied_revision"] == 2
    outcomes = {r["proposal_id"]: r["outcome"] for r in body["results"]}
    assert outcomes[question["proposal_id"]] == "rejected_by_user"
    assert sum(1 for o in outcomes.values() if o == "applied") == 6

    spec = body["revision"]["spec"]
    assert spec["objective"]["status"] == "confirmed"
    assert spec["objective"]["confirmed_by"] == "alice"
    assert spec["objective"]["provenance"]["source"] == "model"
    assert spec["objective"]["provenance"]["model_id"] == "fake:fake-model"
    assert spec["objective"]["provenance"]["prompt_version"] == "business-discovery@1"
    assert spec["domain"]["status"] == "proposed"
    assert {p["name"] for p in spec["personas"]} == {"Operations analyst", "Finance approver"}
    assert all(p["status"] == "proposed" for p in spec["personas"])
    assert spec["open_questions"] == []

    events = client.get(f"/api/v1/projects/{pid}/audit").json()["items"]
    assert [e["action"] for e in events[:3]] == ["ai.proposals.applied", "ai.run.succeeded", "ai.run.started"]
    assert events[0]["details"]["confirmed"] == 1
    assert "Finance ops app" not in str(events)  # descriptions are not copied into the audit trail


def test_apply_twice_is_refused(client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]) -> None:
    ai(ANSWER)
    pid = project["id"]
    run = start(client, pid).json()
    run = client.get(f"/api/v1/projects/{pid}/runs/{run['id']}").json()
    url = f"/api/v1/projects/{pid}/runs/{run['id']}/apply"
    assert client.post(url, json={"decisions": decide(run)}, headers={"If-Match": '"r1"'}).status_code == 200
    again = client.post(url, json={"decisions": decide(run)}, headers={"If-Match": '"r2"'})
    assert again.status_code == 409
    assert again.json()["type"] == "urn:workspace:error:run-already-applied"


def test_apply_requires_current_revision(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER)
    pid = project["id"]
    run = start(client, pid).json()
    url = f"/api/v1/projects/{pid}/runs/{run['id']}/apply"
    run = client.get(f"/api/v1/projects/{pid}/runs/{run['id']}").json()
    assert client.post(url, json={"decisions": decide(run)}).status_code == 428
    assert client.post(url, json={"decisions": decide(run)}, headers={"If-Match": '"r7"'}).status_code == 412


def test_apply_rejects_unknown_or_duplicate_proposals(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER)
    pid = project["id"]
    run = start(client, pid).json()
    url = f"/api/v1/projects/{pid}/runs/{run['id']}/apply"
    decisions = [
        {"proposal_id": "p-objective", "decision": "accept"},
        {"proposal_id": "p-objective", "decision": "confirm"},
        {"proposal_id": "p-made-up", "decision": "accept"},
    ]
    response = client.post(url, json={"decisions": decisions}, headers={"If-Match": '"r1"'})
    assert response.status_code == 422
    assert [e["path"] for e in response.json()["errors"]] == ["/decisions/1/proposal_id", "/decisions/2/proposal_id"]


def test_reject_all_creates_no_revision_but_records_decisions(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ANSWER)
    pid = project["id"]
    run = start(client, pid).json()
    run = client.get(f"/api/v1/projects/{pid}/runs/{run['id']}").json()
    response = client.post(
        f"/api/v1/projects/{pid}/runs/{run['id']}/apply",
        json={"decisions": decide(run, "reject")},
        headers={"If-Match": '"r1"'},
    )
    body = response.json()
    assert body["revision_created"] is False
    assert body["revision"]["revision"] == 1
    assert body["run"]["applied_revision"] is None
    assert set(body["run"]["decisions"].values()) == {"reject"}


def test_failed_run_cannot_be_applied(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai(ModelError(ErrorKind.UNAVAILABLE))
    pid = project["id"]
    run = start(client, pid).json()
    response = client.post(
        f"/api/v1/projects/{pid}/runs/{run['id']}/apply",
        json={"decisions": [{"proposal_id": "p-objective", "decision": "accept"}]},
        headers={"If-Match": '"r1"'},
    )
    assert response.status_code == 409
    assert response.json()["type"] == "urn:workspace:error:run-not-applicable"


def test_confirmed_facts_survive_a_later_run(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider], example_spec: dict[str, Any]
) -> None:
    pid = project["id"]
    put = client.put(f"/api/v1/projects/{pid}/spec", json={"spec": example_spec}, headers={"If-Match": '"r1"'})
    assert put.status_code == 200
    confirmed_objective = put.json()["spec"]["objective"]
    provider = ai(ANSWER)
    run = start(client, pid, skill_id="business-discovery").json()
    run = client.get(f"/api/v1/projects/{pid}/runs/{run['id']}").json()
    assert run["routing"]["method"] == "explicit"
    # The skill does not propose a new objective because it is confirmed...
    assert all(p.get("path") != "/objective" for p in run["proposals"])
    # ...and told the model it is already known.
    assert "Objective: Reduce manual effort" in provider.requests[0][1].content
    apply = client.post(
        f"/api/v1/projects/{pid}/runs/{run['id']}/apply",
        json={"decisions": decide(run, "confirm")},
        headers={"If-Match": '"r2"'},
    )
    assert apply.json()["revision"]["spec"]["objective"] == confirmed_objective


# --------------------------------------------------------------------------- skills and routing


def _put_example(client: TestClient, pid: str, spec: dict[str, Any]) -> None:
    assert (
        client.put(f"/api/v1/projects/{pid}/spec", json={"spec": spec}, headers={"If-Match": '"r1"'}).status_code == 200
    )


def test_skills_report_applicability(client: TestClient, project: dict[str, Any]) -> None:
    items = {s["id"]: s for s in client.get(f"/api/v1/projects/{project['id']}/skills").json()["items"]}
    assert set(items) == {"business-discovery", "acceptance-criteria", "requirements-conflict-detection"}
    assert items["business-discovery"]["applicable"] is True
    assert items["business-discovery"]["message_required"] is True
    assert items["acceptance-criteria"]["applicable"] is False
    assert items["acceptance-criteria"]["unmet_preconditions"] == ["/functional_requirements"]


def test_single_candidate_routing_skips_the_model(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    provider = ai(ANSWER)
    run_id = start(client, project["id"]).json()["id"]
    run = client.get(f"/api/v1/projects/{project['id']}/runs/{run_id}").json()
    assert run["routing"]["method"] == "single-candidate"
    assert run["routing"]["candidates"] == ["business-discovery"]
    assert run["skill_id"] == "business-discovery"
    assert len(provider.requests) == 1  # only the skill call


def test_model_routes_among_several_skills(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider], example_spec: dict[str, Any]
) -> None:
    pid = project["id"]
    _put_example(client, pid, example_spec)
    provider = ai(
        {"skill_id": "acceptance-criteria", "confidence": 0.86, "rationale": "Asks how to test requirements."},
        {
            "criteria": [
                {"requirement_id": "validate-source-files", "given": "a file", "when": "uploaded", "then": "checked"}
            ]
        },
    )
    run_id = start(client, pid, message="How will QA verify file validation?").json()["id"]
    run = client.get(f"/api/v1/projects/{pid}/runs/{run_id}").json()
    assert run["status"] == "succeeded", run["error"]
    assert run["skill_id"] == "acceptance-criteria"
    assert run["routing"]["method"] == "model"
    assert run["routing"]["confidence"] == 0.86
    assert run["routing"]["total_tokens"] == 150
    assert [p["collection"] for p in run["proposals"]] == ["acceptance_criteria"]
    assert run["model"]["prompt_version"] == "acceptance-criteria@1"
    assert len(provider.requests) == 2

    applied = client.post(
        f"/api/v1/projects/{pid}/runs/{run_id}/apply",
        json={"decisions": decide(run)},
        headers={"If-Match": '"r2"'},
    ).json()
    criterion = applied["revision"]["spec"]["acceptance_criteria"][-1]
    assert criterion["requirement_id"] == "validate-source-files"
    assert criterion["provenance"]["skill_id"] == "acceptance-criteria"


def test_routing_to_none_produces_no_proposals(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider], example_spec: dict[str, Any]
) -> None:
    pid = project["id"]
    _put_example(client, pid, example_spec)
    provider = ai({"skill_id": "none", "confidence": 0.9, "rationale": "This is a weather question."})
    run_id = start(client, pid, message="Will it rain tomorrow?").json()["id"]
    run = client.get(f"/api/v1/projects/{pid}/runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["skill_id"] is None
    assert run["proposals"] == []
    assert run["not_applicable_reason"] == "This is a weather question."
    assert len(provider.requests) == 1
    apply = client.post(
        f"/api/v1/projects/{pid}/runs/{run_id}/apply",
        json={"decisions": [{"proposal_id": "p-x", "decision": "accept"}]},
        headers={"If-Match": '"r2"'},
    )
    assert apply.status_code == 409


def test_routing_failure_fails_the_run(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider], example_spec: dict[str, Any]
) -> None:
    pid = project["id"]
    _put_example(client, pid, example_spec)
    ai(ModelError(ErrorKind.UNAVAILABLE, "HTTP 503"))
    run = client.get(f"/api/v1/projects/{pid}/runs/{start(client, pid).json()['id']}").json()
    assert run["status"] == "failed"
    assert run["error"]["kind"] == "provider_unavailable"
    assert run["skill_id"] is None


def test_explicit_skill_must_be_applicable(
    client: TestClient, project: dict[str, Any], ai: Callable[..., FakeProvider]
) -> None:
    ai()
    response = start(client, project["id"], message="criteria please", skill_id="acceptance-criteria")
    assert response.status_code == 422
    body = response.json()
    assert body["type"] == "urn:workspace:error:skill-not-applicable"
    assert "/functional_requirements" in body["detail"]
    assert start(client, project["id"], skill_id="no-such-skill").status_code == 422
