"""HTTP routes for API v1. Handlers stay thin: parse, authorize, delegate to ``service``."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from appspec import ApplicationSpec, json_schema
from design_system import DesignSystemContract
from skill_sdk import SkillRegistry

from . import builds, code, runs, service, ui, workflows
from .ai import ModelRuntime
from .auth import CurrentPrincipal
from .errors import Problem
from .schemas import (
    AiStatus,
    ApplyRunRequest,
    ApplyRunResult,
    AuditPage,
    BuildOut,
    BuildPage,
    CodeDiff,
    CodeFile,
    CodeManifest,
    DesignSystemList,
    Health,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    RunCreate,
    RunOut,
    RunPage,
    SafetyScan,
    SafetyScanRequest,
    SkillList,
    SpecRevisionOut,
    SpecRevisionPage,
    SpecUpdate,
    SpecValidationResult,
    UiPreview,
    WorkflowCreate,
    WorkflowDefinitionList,
    WorkflowOut,
    WorkflowPage,
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


@api.post(
    "/safety/scan",
    response_model=SafetyScan,
    tags=["ai"],
    summary="Screen request text for prompt-injection signals before starting a run (deterministic, no model)",
)
def scan_text(body: SafetyScanRequest, principal: CurrentPrincipal) -> SafetyScan:
    return runs.scan(body.text)


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
    request: Request,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    background: BackgroundTasks,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ApplyRunResult:
    runtime = _runtime(request)
    registry = _registry(request)
    result, next_runs = runs.apply_run(session, principal, project_id, run_id, if_match, body, runtime, registry)
    _schedule(request, background, next_runs, runtime, registry)
    response.headers["ETag"] = service.etag(result.revision.revision)
    return result


def _schedule(
    request: Request,
    background: BackgroundTasks,
    run_ids: list[uuid.UUID],
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> None:
    if runtime is None:
        return
    for run_id in run_ids:
        background.add_task(runs.execute_run, request.app.state.db, run_id, runtime, registry)


# --------------------------------------------------------------------------- workflows

WorkflowId = Annotated[uuid.UUID, Path(description="Workflow identifier.")]


@api.get(
    "/workflow-definitions",
    response_model=WorkflowDefinitionList,
    tags=["workflows"],
    summary="Built-in multi-step workflows",
)
def list_workflow_definitions(principal: CurrentPrincipal) -> WorkflowDefinitionList:
    return workflows.list_definitions()


@api.post(
    "/projects/{project_id}/workflows",
    response_model=WorkflowOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["workflows"],
    summary="Start a multi-step workflow; it pauses for review after each step that proposes changes",
    responses={
        200: {"model": WorkflowOut, "description": "Replay of an earlier request with the same Idempotency-Key."},
        403: _PROBLEM,
        409: _PROBLEM,
        429: _PROBLEM,
        503: _PROBLEM,
    },
)
def start_project_workflow(
    project_id: ProjectId,
    body: WorkflowCreate,
    request: Request,
    principal: CurrentPrincipal,
    session: DbSession,
    response: Response,
    background: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> WorkflowOut:
    runtime = _runtime(request)
    registry = _registry(request)
    wf, created, next_runs = workflows.start_workflow(
        session, principal, project_id, body, idempotency_key, runtime, registry
    )
    response.headers["Location"] = f"/api/v1/projects/{project_id}/workflows/{wf.id}"
    if not created:
        response.status_code = status.HTTP_200_OK
    _schedule(request, background, next_runs, runtime, registry)
    return wf


@api.get(
    "/projects/{project_id}/workflows",
    response_model=WorkflowPage,
    tags=["workflows"],
    summary="Recent workflows, newest first",
)
def list_project_workflows(
    project_id: ProjectId, request: Request, principal: CurrentPrincipal, session: DbSession
) -> WorkflowPage:
    return workflows.list_workflows(session, principal, project_id, _registry(request))


@api.get(
    "/projects/{project_id}/workflows/{workflow_id}",
    response_model=WorkflowOut,
    tags=["workflows"],
    summary="One workflow with its step checkpoint",
)
def get_project_workflow(
    project_id: ProjectId, workflow_id: WorkflowId, request: Request, principal: CurrentPrincipal, session: DbSession
) -> WorkflowOut:
    return workflows.get_workflow(session, principal, project_id, workflow_id, _registry(request))


@api.post(
    "/projects/{project_id}/workflows/{workflow_id}/resume",
    response_model=WorkflowOut,
    tags=["workflows"],
    summary="Retry a failed step (bounded) or restart a stalled one",
    responses={409: _PROBLEM, 503: _PROBLEM},
)
def resume_project_workflow(
    project_id: ProjectId,
    workflow_id: WorkflowId,
    request: Request,
    principal: CurrentPrincipal,
    session: DbSession,
    background: BackgroundTasks,
) -> WorkflowOut:
    runtime = _runtime(request)
    registry = _registry(request)
    wf, next_runs = workflows.resume_workflow(session, principal, project_id, workflow_id, runtime, registry)
    _schedule(request, background, next_runs, runtime, registry)
    return wf


@api.post(
    "/projects/{project_id}/workflows/{workflow_id}/cancel",
    response_model=WorkflowOut,
    tags=["workflows"],
    summary="Cancel a workflow; a step run already in progress finishes but nothing further starts",
    responses={409: _PROBLEM},
)
def cancel_project_workflow(
    project_id: ProjectId, workflow_id: WorkflowId, principal: CurrentPrincipal, session: DbSession
) -> WorkflowOut:
    return workflows.cancel_workflow(session, principal, project_id, workflow_id)


# --------------------------------------------------------------------------- design systems and UI preview


@api.get(
    "/design-systems",
    response_model=DesignSystemList,
    tags=["design"],
    summary="Built-in design-system contracts",
)
def list_design_systems(principal: CurrentPrincipal) -> DesignSystemList:
    return ui.list_design_systems()


@api.get(
    "/design-systems/{design_system_id}",
    response_model=DesignSystemContract,
    tags=["design"],
    summary="One design-system contract: component mappings, tokens and rules",
)
def get_design_system(
    design_system_id: Annotated[str, Path(max_length=64)], principal: CurrentPrincipal
) -> DesignSystemContract:
    return ui.get_design_system(design_system_id)


@api.get(
    "/projects/{project_id}/ui",
    response_model=UiPreview,
    tags=["design"],
    summary="UI IR derived from a spec revision, its issues, and its rendering with the project's design system",
)
def get_project_ui(
    project_id: ProjectId,
    principal: CurrentPrincipal,
    session: DbSession,
    revision: Annotated[int | None, Query(ge=1, description="Spec revision; defaults to the current one.")] = None,
) -> UiPreview:
    return ui.preview(session, principal, project_id, revision)


# --------------------------------------------------------------------------- generated code

Revision = Annotated[int | None, Query(ge=1, description="Spec revision; defaults to the current one.")]


@api.get(
    "/projects/{project_id}/code",
    response_model=CodeManifest,
    tags=["code"],
    summary="Generated React + Fluent 2 project for a spec revision: file list, hashes and warnings",
)
def get_project_code(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, revision: Revision = None
) -> CodeManifest:
    return code.manifest(session, principal, project_id, revision)


@api.get(
    "/projects/{project_id}/code/file",
    response_model=CodeFile,
    tags=["code"],
    summary="One generated file",
)
def get_project_code_file(
    project_id: ProjectId,
    principal: CurrentPrincipal,
    session: DbSession,
    path: Annotated[str, Query(min_length=1, max_length=200)],
    revision: Revision = None,
) -> CodeFile:
    return code.file(session, principal, project_id, path, revision)


@api.get(
    "/projects/{project_id}/code/diff",
    response_model=CodeDiff,
    tags=["code"],
    summary="Unified diff of the generated code between two spec revisions",
)
def get_project_code_diff(
    project_id: ProjectId,
    principal: CurrentPrincipal,
    session: DbSession,
    base: Annotated[int, Query(ge=1, alias="from", description="Older spec revision.")],
    head: Annotated[int | None, Query(ge=1, alias="to", description="Newer revision; defaults to current.")] = None,
) -> CodeDiff:
    return code.diff(session, principal, project_id, base, head)


@api.get(
    "/projects/{project_id}/code.zip",
    tags=["code"],
    summary="Download the generated project as a zip archive",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}, "description": "Deterministic zip of the generated project."}},
)
def download_project_code(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, revision: Revision = None
) -> Response:
    filename, data = code.archive(session, principal, project_id, revision)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- isolated builds (ADR-0015)


@api.post(
    "/projects/{project_id}/builds",
    response_model=BuildOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["builds"],
    summary="Queue a build of the generated project in the isolated runner",
    description=(
        "The API only records the request; a separate worker builds the project in a container with no "
        "network and no credentials (ADR-0015). One active build per project."
    ),
)
def create_build(
    project_id: ProjectId, principal: CurrentPrincipal, session: DbSession, revision: Revision = None
) -> BuildOut:
    return builds.request_build(session, principal, project_id, revision)


@api.get("/projects/{project_id}/builds", response_model=BuildPage, tags=["builds"], summary="Recent builds")
def list_project_builds(project_id: ProjectId, principal: CurrentPrincipal, session: DbSession) -> BuildPage:
    return builds.list_builds(session, principal, project_id)


@api.get("/projects/{project_id}/builds/{build_id}", response_model=BuildOut, tags=["builds"], summary="One build")
def get_project_build(
    project_id: ProjectId,
    build_id: Annotated[uuid.UUID, Path(description="Build identifier.")],
    principal: CurrentPrincipal,
    session: DbSession,
) -> BuildOut:
    return builds.get_build(session, principal, project_id, build_id)
