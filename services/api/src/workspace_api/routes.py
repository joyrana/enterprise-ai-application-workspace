"""HTTP routes for API v1. Handlers stay thin: parse, authorize, delegate to ``service``."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from appspec import ApplicationSpec, json_schema
from skill_sdk import SkillRegistry

from . import runs, service
from .ai import ModelRuntime
from .auth import CurrentPrincipal
from .errors import Problem
from .schemas import (
    AiStatus,
    ApplyRunRequest,
    ApplyRunResult,
    AuditPage,
    Health,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    RunCreate,
    RunOut,
    RunPage,
    SkillList,
    SpecRevisionOut,
    SpecRevisionPage,
    SpecUpdate,
    SpecValidationResult,
)


def get_session(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


DbSession = Annotated[Session, Depends(get_session)]
ProjectId = Annotated[uuid.UUID, Path(description="Project identifier.")]
Limit = Annotated[int, Query(ge=1, le=100, description="Page size.")]
Cursor = Annotated[str | None, Query(max_length=512, description="Opaque cursor from a previous page.")]

_PROBLEM = {"model": Problem, "content": {"application/problem+json": {}}}
COMMON_ERRORS: dict[int | str, dict[str, Any]] = {
    400: _PROBLEM,
    401: _PROBLEM,
    404: _PROBLEM,
    413: _PROBLEM,
    422: _PROBLEM,
}

api = APIRouter(prefix="/api/v1", responses=COMMON_ERRORS)
ops = APIRouter(tags=["operations"])


# --------------------------------------------------------------------------- operations


@ops.get("/healthz", response_model=Health, summary="Liveness")
def healthz() -> Health:
    return Health(status="ok")


@ops.get("/readyz", response_model=Health, summary="Readiness (database reachable)", responses={503: _PROBLEM})
def readyz(session: DbSession, response: Response) -> Health:
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="unavailable")
    return Health(status="ok")


# --------------------------------------------------------------------------- projects


@api.post(
    "/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    tags=["projects"],
    summary="Create a project with an initial, empty specification (revision 1)",
    responses={
        200: {"model": ProjectOut, "description": "Replay of an earlier request with the same Idempotency-Key."},
        409: _PROBLEM,
    },
)
def create_project(
    body: ProjectCreate,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProjectOut:
    result = service.create_project(session, principal, body, idempotency_key)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/api/v1/projects/{result.project.id}"
    return result.project


@api.get("/projects", response_model=ProjectPage, tags=["projects"], summary="List projects, newest first")
def list_projects(
    principal: CurrentPrincipal, session: DbSession, limit: Limit = 20, cursor: Cursor = None
) -> ProjectPage:
    return service.list_projects(session, principal, limit, cursor)


@api.get("/projects/{project_id}", response_model=ProjectOut, tags=["projects"], summary="Get a project")
def get_project(project_id: ProjectId, principal: CurrentPrincipal, session: DbSession) -> ProjectOut:
    return service.get_project(session, principal, project_id)


# --------------------------------------------------------------------------- specification


@api.get(
    "/projects/{project_id}/spec",
    response_model=SpecRevisionOut,
    tags=["specification"],
    summary="Get the current specification; the ETag identifies its revision",
)
def get_spec(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, response: Response
) -> SpecRevisionOut:
    out = service.get_spec(session, principal, project_id)
    response.headers["ETag"] = service.etag(out.revision)
    return out


@api.put(
    "/projects/{project_id}/spec",
    response_model=SpecRevisionOut,
    tags=["specification"],
    summary="Save a new specification revision (optimistic concurrency via If-Match)",
    responses={412: _PROBLEM, 428: _PROBLEM},
)
def put_spec(
    project_id: ProjectId,
    body: SpecUpdate,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SpecRevisionOut:
    result = service.update_spec(session, principal, project_id, if_match, body)
    response.headers["ETag"] = service.etag(result.revision.revision)
    response.headers["X-Revision-Created"] = "true" if result.created else "false"
    return result.revision


@api.post(
    "/projects/{project_id}/spec/validate",
    response_model=SpecValidationResult,
    tags=["specification"],
    summary="Validate a candidate specification without saving it",
)
def validate_spec(
    project_id: ProjectId, body: ApplicationSpec, principal: CurrentPrincipal, session: DbSession
) -> SpecValidationResult:
    return service.validate_candidate(session, principal, project_id, body)


@api.get(
    "/projects/{project_id}/spec/revisions",
    response_model=SpecRevisionPage,
    tags=["specification"],
    summary="List specification revisions, newest first",
)
def list_revisions(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, limit: Limit = 20, cursor: Cursor = None
) -> SpecRevisionPage:
    return service.list_revisions(session, principal, project_id, limit, cursor)


@api.get(
    "/projects/{project_id}/spec/revisions/{revision}",
    response_model=SpecRevisionOut,
    tags=["specification"],
    summary="Get a specific specification revision",
)
def get_revision(
    project_id: ProjectId,
    revision: Annotated[int, Path(ge=1)],
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
) -> SpecRevisionOut:
    out = service.get_spec(session, principal, project_id, revision)
    response.headers["ETag"] = service.etag(out.revision)
    return out


@api.get("/projects/{project_id}/audit", response_model=AuditPage, tags=["audit"], summary="Project audit trail")
def list_audit(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, limit: Limit = 50, cursor: Cursor = None
) -> AuditPage:
    return service.list_audit(session, principal, project_id, limit, cursor)


# --------------------------------------------------------------------------- schemas


@api.get("/schemas/application-spec", tags=["schemas"], summary="JSON Schema of the current specification version")
def application_spec_schema() -> dict[str, Any]:
    return json_schema()


# --------------------------------------------------------------------------- AI


def _runtime(request: Request) -> ModelRuntime | None:
    runtime = request.app.state.model_runtime
    return runtime if isinstance(runtime, ModelRuntime) else None


def _registry(request: Request) -> SkillRegistry:
    registry = request.app.state.skill_registry
    assert isinstance(registry, SkillRegistry)
    return registry


RunId = Annotated[uuid.UUID, Path(description="Run identifier.")]


@api.get("/ai/status", response_model=AiStatus, tags=["ai"], summary="Which model (if any) is configured")
def ai_status(request: Request, principal: CurrentPrincipal) -> AiStatus:
    runtime = _runtime(request)
    if runtime is None:
        return AiStatus(configured=False, model=None, profile=None, remote=None, structured_mode=None)
    return AiStatus(
        configured=True,
        model=runtime.label,
        profile=runtime.profile,
        remote=runtime.capabilities.remote,
        structured_mode=runtime.capabilities.structured_mode.value,
    )


@api.get(
    "/projects/{project_id}/skills",
    response_model=SkillList,
    tags=["ai"],
    summary="Skills and whether each can run on this project now",
)
def list_project_skills(
    project_id: ProjectId, request: Request, principal: CurrentPrincipal, session: DbSession
) -> SkillList:
    return runs.list_skills(session, principal, project_id, _registry(request))


@api.post(
    "/projects/{project_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["ai"],
    summary="Start an AI run: route the message to a skill (or use skill_id) and poll for proposals",
    responses={
        200: {"model": RunOut, "description": "Replay of an earlier request with the same Idempotency-Key."},
        403: _PROBLEM,
        409: _PROBLEM,
        429: _PROBLEM,
        503: _PROBLEM,
    },
)
def start_run(
    project_id: ProjectId,
    body: RunCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunOut:
    runtime = _runtime(request)
    registry = _registry(request)
    run, created = runs.create_run(session, principal, project_id, body, idempotency_key, runtime, registry)
    response.headers["Location"] = f"/api/v1/projects/{project_id}/runs/{run.id}"
    if created and runtime is not None:
        background.add_task(runs.execute_run, request.app.state.db, run.id, runtime, registry)
    else:
        response.status_code = status.HTTP_200_OK
    return run


@api.get(
    "/projects/{project_id}/runs",
    response_model=RunPage,
    tags=["ai"],
    summary="Recent AI runs, newest first (resume after a page refresh)",
)
def list_project_runs(
    project_id: ProjectId, request: Request, principal: CurrentPrincipal, session: DbSession
) -> RunPage:
    return runs.list_runs(session, principal, project_id, _registry(request))


@api.get(
    "/projects/{project_id}/runs/{run_id}",
    response_model=RunOut,
    tags=["ai"],
    summary="Get an AI run, its routing decision and proposals",
)
def get_project_run(
    project_id: ProjectId, run_id: RunId, request: Request, principal: CurrentPrincipal, session: DbSession
) -> RunOut:
    return runs.get_run(session, principal, project_id, run_id, _registry(request))


@api.post(
    "/projects/{project_id}/runs/{run_id}/apply",
    response_model=ApplyRunResult,
    tags=["ai"],
    summary="Apply per-proposal decisions (accept, confirm, reject) as one new revision",
    responses={409: _PROBLEM, 412: _PROBLEM, 428: _PROBLEM},
)
def apply_project_run(
    project_id: ProjectId,
    run_id: RunId,
    body: ApplyRunRequest,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ApplyRunResult:
    result = runs.apply_run(session, principal, project_id, run_id, if_match, body)
    response.headers["ETag"] = service.etag(result.revision.revision)
    return result
