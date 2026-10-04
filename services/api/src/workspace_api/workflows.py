"""Multi-step workflows: persistence and orchestration around ``skill_sdk.workflow`` (ADR-0012).

The checkpoint (``workflows.state``) is always written in the same transaction
as the event that changed it: creating a step run, a step run finishing
(inside ``runs.execute_run``), a person applying a step's proposals (inside
``runs.apply_run``), a resume or a cancel. Functions here never commit; their
callers do, and they return the ids of step runs the caller must execute after
committing.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from appspec import ApplicationSpec
from skill_sdk import SkillRegistry, unmet_preconditions
from skill_sdk.workflow import (
    BUILT_IN_WORKFLOWS,
    TERMINAL,
    RunOutcome,
    StartStep,
    StepStatus,
    WorkflowDefinition,
    WorkflowError,
    WorkflowState,
    WorkflowStatus,
    advance,
    cancel,
    resume,
    run_applied,
    run_finished,
    step_started,
)
from skill_sdk.workflow import start as initial_state

from . import runs, service
from .ai import ModelRuntime
from .auth import Principal
from .db import Project, Workflow, WorkflowRun
from .errors import IdempotencyConflict, ModelNotConfigured, ModelPolicyDenied, NotFound, WorkflowStateConflict
from .schemas import (
    WorkflowCreate,
    WorkflowDefinitionList,
    WorkflowDefinitionOut,
    WorkflowOut,
    WorkflowPage,
    WorkflowStepDefinitionOut,
    WorkflowStepOut,
)

_ACTIVE = ("queued", "running")


class InvalidRequest(service.InvalidRequest):
    pass


def _definition(definition_id: str, version: str | None = None) -> WorkflowDefinition:
    definition = BUILT_IN_WORKFLOWS.get(definition_id)
    if definition is None or (version is not None and definition.version != version):
        raise NotFound(f"Workflow definition '{definition_id}' was not found.")
    return definition


def list_definitions() -> WorkflowDefinitionList:
    return WorkflowDefinitionList(
        items=[
            WorkflowDefinitionOut(
                id=d.id,
                version=d.version,
                name=d.name,
                description=d.description,
                steps=[WorkflowStepDefinitionOut(id=s.id, title=s.title, skill_id=s.skill_id) for s in d.steps],
                max_attempts_per_step=d.max_attempts_per_step,
            )
            for d in BUILT_IN_WORKFLOWS.values()
        ]
    )


# --------------------------------------------------------------------------- output


def _state(wf: Workflow) -> WorkflowState:
    return WorkflowState.model_validate(wf.state)


def _active_run(session: Session, wf: Workflow, state: WorkflowState) -> WorkflowRun | None:
    step = state.step
    if step is None or not step.run_ids:
        return None
    run = session.get(WorkflowRun, uuid.UUID(step.run_ids[-1]))
    return run if run is not None and run.status in _ACTIVE else None


def _out(session: Session, wf: Workflow) -> WorkflowOut:
    definition = _definition(wf.definition_id, wf.definition_version)
    state = _state(wf)
    active = _active_run(session, wf, state)
    step = state.step
    can_resume = False
    if state.status not in TERMINAL and step is not None:
        if step.status is StepStatus.FAILED:
            can_resume = step.attempts < definition.max_attempts_per_step
        elif step.status is StepStatus.PENDING:
            can_resume = True  # stalled: its run was never created
    return WorkflowOut(
        id=wf.id,
        definition_id=wf.definition_id,
        definition_version=wf.definition_version,
        name=definition.name,
        status=state.status.value,
        current_step=state.current,
        steps=[
            WorkflowStepOut(
                id=s.step_id,
                title=d.title,
                skill_id=d.skill_id,
                status=s.status.value,
                attempts=s.attempts,
                run_ids=[uuid.UUID(r) for r in s.run_ids],
                reason=s.reason,
                applied_revision=s.applied_revision,
            )
            for s, d in zip(state.steps, definition.steps, strict=True)
        ],
        message=str(wf.input.get("message", "")),
        active_run_id=active.id if active else None,
        can_resume=can_resume,
        created_by=wf.created_by,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        finished_at=wf.finished_at,
    )


def _save(session: Session, principal: Principal, wf: Workflow, before: WorkflowState, after: WorkflowState) -> None:
    wf.state = after.model_dump(mode="json")
    wf.status = after.status.value
    wf.updated_at = datetime.now(UTC)
    if after.status in TERMINAL and wf.finished_at is None:
        wf.finished_at = wf.updated_at
    for i, (old, new) in enumerate(zip(before.steps, after.steps, strict=True)):
        if old.status is not StepStatus.SKIPPED and new.status is StepStatus.SKIPPED:
            service.audit(
                session,
                principal,
                wf.project_id,
                "workflow.step_skipped",
                workflow_id=str(wf.id),
                step=i,
                reason=new.reason,
            )
    if before.status is not after.status and after.status in (
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    ):
        step = after.step
        service.audit(
            session,
            principal,
            wf.project_id,
            f"workflow.{after.status.value}",
            workflow_id=str(wf.id),
            step=after.current if step is not None else None,
            reason=step.reason if step is not None else None,
        )


# --------------------------------------------------------------------------- driving


def _drive(
    session: Session,
    principal: Principal,
    wf: Workflow,
    project: Project,
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> list[uuid.UUID]:
    """Advance past finished/skippable steps and create the next step's run, if any."""
    definition = _definition(wf.definition_id, wf.definition_version)
    before = _state(wf)
    spec = service.current_spec(session, project)

    def unmet(skill_id: str) -> list[str]:
        return unmet_preconditions(registry.get(skill_id).manifest, spec)

    state, action = advance(definition, before, str(wf.input.get("message", "")), unmet)
    created: list[uuid.UUID] = []
    if isinstance(action, StartStep):
        problem = _cannot_run(runtime, spec)
        if problem is not None:
            step = state.steps[action.index]
            step.status = StepStatus.FAILED
            step.reason = problem
            state.status = WorkflowStatus.FAILED
        else:
            assert runtime is not None
            manifest = registry.get(action.skill_id).manifest
            run = runs.new_run(
                session,
                principal,
                project,
                message=action.message,
                skill_id=manifest.id,
                skill_version=manifest.version,
                model_label=runtime.label,
                workflow_id=wf.id,
                workflow_step=action.index,
            )
            session.flush()
            state = step_started(definition, state, action.index, str(run.id))
            created.append(run.id)
    _save(session, principal, wf, before, state)
    return created


def _cannot_run(runtime: ModelRuntime | None, spec: ApplicationSpec) -> str | None:
    if runtime is None:
        return "No AI model is configured."
    return runs.data_policy_problem(runtime, spec)


def _lock(session: Session, workflow_id: uuid.UUID, tenant_id: str, project_id: uuid.UUID | None = None) -> Workflow:
    stmt = select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id).with_for_update()
    if project_id is not None:
        stmt = stmt.where(Workflow.project_id == project_id)
    wf = session.scalars(stmt).one_or_none()
    if wf is None:
        raise NotFound(f"Workflow {workflow_id} was not found.")
    return wf


def _outcome(run: WorkflowRun) -> tuple[RunOutcome, str | None]:
    result = run.result or {}
    if run.status == "failed":
        return "failed", str((run.error or {}).get("message") or "The step's run failed.")
    if result.get("proposals"):
        return "proposals", None
    return "empty", result.get("not_applicable_reason") or result.get("summary") or "Nothing to propose."


# --------------------------------------------------------------------------- hooks (callers commit)


def on_run_finished(
    session: Session, run: WorkflowRun, runtime: ModelRuntime | None, registry: SkillRegistry
) -> list[uuid.UUID]:
    """Record a finished step run; start the next step when no review is needed."""
    assert run.workflow_id is not None
    principal = Principal(tenant_id=run.tenant_id, user_id=run.created_by)
    wf = _lock(session, run.workflow_id, run.tenant_id)
    before = _state(wf)
    outcome, reason = _outcome(run)
    state = run_finished(before, str(run.id), outcome, reason)
    _save(session, principal, wf, before, state)
    if state.status is WorkflowStatus.RUNNING:
        project = service.find_project(session, principal, wf.project_id)
        return _drive(session, principal, wf, project, runtime, registry)
    return []


def on_run_applied(
    session: Session,
    principal: Principal,
    run: WorkflowRun,
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> list[uuid.UUID]:
    """The person decided on a step's proposals: complete the step and start the next one."""
    assert run.workflow_id is not None
    wf = _lock(session, run.workflow_id, principal.tenant_id)
    before = _state(wf)
    state = run_applied(before, str(run.id), run.applied_revision)
    _save(session, principal, wf, before, state)
    if state != before and state.status is WorkflowStatus.RUNNING:
        project = service.find_project(session, principal, wf.project_id)
        return _drive(session, principal, wf, project, runtime, registry)
    return []


def _reconcile(session: Session, wf: Workflow, registry: SkillRegistry) -> None:
    """Catch up with a step run that ended without updating the checkpoint (process stopped)."""
    state = _state(wf)
    step = state.step
    if state.status in TERMINAL or step is None or step.status is not StepStatus.RUNNING or not step.run_ids:
        return
    run = session.get(WorkflowRun, uuid.UUID(step.run_ids[-1]))
    if run is None:
        return
    runs.expire_if_stale(session, run, registry)
    if run.status in _ACTIVE:
        return
    wf = _lock(session, wf.id, wf.tenant_id)
    before = _state(wf)
    outcome, reason = _outcome(run)
    after = run_finished(before, str(run.id), outcome, reason)
    if after != before:
        _save(session, Principal(tenant_id=wf.tenant_id, user_id=run.created_by), wf, before, after)
    session.commit()


# --------------------------------------------------------------------------- API operations


def start_workflow(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID,
    body: WorkflowCreate,
    idempotency_key: str | None,
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> tuple[WorkflowOut, bool, list[uuid.UUID]]:
    project = service.find_project(session, principal, project_id, lock=True)
    definition = _definition(body.definition_id)
    fingerprint = None
    if idempotency_key is not None:
        if not runs.IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise InvalidRequest("Idempotency-Key must be 8-128 characters of [A-Za-z0-9._:-].")
        fingerprint = "sha256:" + hashlib.sha256(f"wf:{project_id}:{body.model_dump_json()}".encode()).hexdigest()
        existing = session.scalars(
            select(Workflow).where(
                Workflow.tenant_id == principal.tenant_id, Workflow.idempotency_key == idempotency_key
            )
        ).one_or_none()
        if existing is not None:
            if existing.idempotency_fingerprint != fingerprint:
                raise IdempotencyConflict("This Idempotency-Key was already used with a different request.")
            return _out(session, existing), False, []

    if runtime is None:
        raise ModelNotConfigured(
            "Set MODEL_PROFILE and MODEL_ID (see .env.example and docs/adr/0007-model-providers.md)."
        )
    spec = service.current_spec(session, project)
    problem = runs.data_policy_problem(runtime, spec)
    if problem is not None:
        raise ModelPolicyDenied(problem)
    runs.check_active_limit(session, principal)

    wf = Workflow(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project.id,
        definition_id=definition.id,
        definition_version=definition.version,
        status=WorkflowStatus.RUNNING.value,
        state=initial_state(definition).model_dump(mode="json"),
        input={"message": body.message},
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
    )
    session.add(wf)
    session.flush()
    service.audit(
        session,
        principal,
        project.id,
        "workflow.started",
        workflow_id=str(wf.id),
        definition=f"{definition.id}@{definition.version}",
        message_chars=len(body.message),
    )
    created = _drive(session, principal, wf, project, runtime, registry)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise IdempotencyConflict("A concurrent request used the same Idempotency-Key.") from None
    session.refresh(wf)
    return _out(session, wf), True, created


def get_workflow(
    session: Session, principal: Principal, project_id: uuid.UUID, workflow_id: uuid.UUID, registry: SkillRegistry
) -> WorkflowOut:
    service.find_project(session, principal, project_id)
    wf = session.scalars(
        select(Workflow).where(
            Workflow.id == workflow_id, Workflow.tenant_id == principal.tenant_id, Workflow.project_id == project_id
        )
    ).one_or_none()
    if wf is None:
        raise NotFound(f"Workflow {workflow_id} was not found.")
    _reconcile(session, wf, registry)
    session.refresh(wf)
    return _out(session, wf)


def list_workflows(
    session: Session, principal: Principal, project_id: uuid.UUID, registry: SkillRegistry
) -> WorkflowPage:
    service.find_project(session, principal, project_id)
    rows = list(
        session.scalars(
            select(Workflow)
            .where(Workflow.tenant_id == principal.tenant_id, Workflow.project_id == project_id)
            .order_by(Workflow.created_at.desc(), Workflow.id.desc())
            .limit(20)
        )
    )
    for wf in rows:
        _reconcile(session, wf, registry)
        session.refresh(wf)
    return WorkflowPage(items=[_out(session, wf) for wf in rows])


def resume_workflow(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID,
    workflow_id: uuid.UUID,
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> tuple[WorkflowOut, list[uuid.UUID]]:
    project = service.find_project(session, principal, project_id)
    wf = _lock(session, workflow_id, principal.tenant_id, project_id)
    _reconcile(session, wf, registry)
    wf = _lock(session, workflow_id, principal.tenant_id, project_id)
    definition = _definition(wf.definition_id, wf.definition_version)
    before = _state(wf)
    try:
        state = resume(definition, before)
    except WorkflowError as exc:
        raise WorkflowStateConflict(str(exc)) from exc
    if runtime is None:
        raise ModelNotConfigured("Set MODEL_PROFILE and MODEL_ID to resume this workflow.")
    _save(session, principal, wf, before, state)
    service.audit(session, principal, project.id, "workflow.resumed", workflow_id=str(wf.id), step=state.current)
    created = _drive(session, principal, wf, project, runtime, registry)
    session.commit()
    session.refresh(wf)
    return _out(session, wf), created


def cancel_workflow(
    session: Session, principal: Principal, project_id: uuid.UUID, workflow_id: uuid.UUID
) -> WorkflowOut:
    service.find_project(session, principal, project_id)
    wf = _lock(session, workflow_id, principal.tenant_id, project_id)
    before = _state(wf)
    try:
        state = cancel(before)
    except WorkflowError as exc:
        raise WorkflowStateConflict(str(exc)) from exc
    _save(session, principal, wf, before, state)
    session.commit()
    session.refresh(wf)
    return _out(session, wf)
