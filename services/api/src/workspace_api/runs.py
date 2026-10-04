"""AI runs: route a request to a skill, execute it in the background, apply decisions.

Lifecycle: ``queued`` → ``running`` → ``succeeded`` | ``failed``. Execution first
routes the request (ADR-0009): an explicit skill is used as-is; otherwise the
precondition filter runs, and the model chooses only when several skills apply.
A succeeded run holds proposals; applying the person's decisions creates at most
one new spec revision and can happen only once per run.

Execution happens after the HTTP response (FastAPI background task) in its own
database session. State is durable: if the process stops mid-run, the run is
marked ``failed`` with kind ``interrupted`` once it is older than its deadline.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from appspec import ApplicationSpec, Provenance, Source
from model_gateway import Budget, ModelError, check_data_policy
from skill_sdk import (
    Decision,
    Outcome,
    RoutingError,
    SkillContext,
    SkillRegistry,
    SkillRouter,
    SpecCommand,
    apply_commands,
    unmet_preconditions,
)

from . import service
from .ai import ModelRuntime
from .auth import Principal
from .db import Database, WorkflowRun
from .errors import (
    FieldError,
    IdempotencyConflict,
    ModelNotConfigured,
    ModelPolicyDenied,
    NotFound,
    RunAlreadyApplied,
    RunNotApplicable,
    SkillNotApplicable,
    SpecInvalid,
    TooManyRuns,
)
from .schemas import (
    ApplyRunRequest,
    ApplyRunResult,
    ModelUsage,
    RunCreate,
    RunError,
    RunModelInfo,
    RunOut,
    RunPage,
    RunRouting,
    SkillInfo,
    SkillList,
)

log = logging.getLogger("workspace_api.runs")

MAX_ACTIVE_RUNS_PER_TENANT = 3
ROUTING_DEADLINE_S = 60.0
_STALE_GRACE = timedelta(seconds=60)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_COMMANDS = TypeAdapter(list[SpecCommand])


class InvalidRequest(service.InvalidRequest):
    pass


def _classification(spec: ApplicationSpec) -> str | None:
    value = spec.security.classification.value
    return value.value if value is not None else None


def _model_info(raw: dict[str, Any] | None) -> RunModelInfo | None:
    if not raw:
        return None
    usage = raw.get("usage") or {}
    calls = raw.get("calls") or []
    return RunModelInfo(
        model_id=str(raw.get("model_id", "")),
        profile=str(raw.get("profile", "")),
        prompt_version=raw.get("prompt_version"),
        usage=ModelUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
        ),
        repaired=bool(raw.get("repaired", False)),
        calls=len(calls),
        latency_ms=round(sum(float(c.get("latency_ms", 0)) for c in calls), 1),
        estimated_cost_usd=raw.get("estimated_cost_usd"),
    )


def _routing_out(raw: dict[str, Any] | None) -> RunRouting | None:
    if not raw:
        return None
    model = raw.get("model") or {}
    return RunRouting(
        method=str(raw.get("method", "")),
        candidates=list(raw.get("candidates", [])),
        chosen=raw.get("skill_id"),
        confidence=raw.get("confidence"),
        rationale=str(raw.get("rationale", "")),
        model_id=model.get("model_id"),
        total_tokens=int((model.get("usage") or {}).get("total_tokens", 0)),
    )


def _message(run: WorkflowRun) -> str:
    return str(run.input.get("message") or run.input.get("description") or "")


def _run_out(run: WorkflowRun) -> RunOut:
    result = run.result or {}
    return RunOut(
        id=run.id,
        skill_id=run.skill_id,
        skill_version=run.skill_version,
        status=run.status,
        message=_message(run),
        routing=_routing_out(run.routing),
        base_revision=run.base_revision,
        summary=result.get("summary"),
        not_applicable_reason=result.get("not_applicable_reason"),
        proposals=_COMMANDS.validate_python(result.get("proposals", [])),
        model=_model_info(run.model),
        error=RunError.model_validate(run.error) if run.error else None,
        applied_revision=run.applied_revision,
        decisions=run.decisions,
        created_by=run.created_by,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _run(
    session: Session, principal: Principal, project_id: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False
) -> WorkflowRun:
    stmt = select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.project_id == project_id, WorkflowRun.tenant_id == principal.tenant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    run = session.scalars(stmt).one_or_none()
    if run is None:
        raise NotFound(f"Run {run_id} was not found.")
    return run


def _deadline_s(run: WorkflowRun, registry: SkillRegistry) -> float:
    skill_timeout = 0.0
    if run.skill_id:
        try:
            skill_timeout = registry.get(run.skill_id, run.skill_version).manifest.timeout_s
        except Exception:  # an old run of a skill version no longer registered
            skill_timeout = 0.0
    longest = max((m.timeout_s for m in registry.manifests()), default=180.0)
    return ROUTING_DEADLINE_S + (skill_timeout or longest)


def _expire_if_stale(session: Session, run: WorkflowRun, registry: SkillRegistry) -> None:
    """Mark runs that can no longer finish (process stopped) as interrupted."""
    if run.status not in ("queued", "running"):
        return
    reference = run.started_at or run.created_at
    if datetime.now(UTC) - reference <= timedelta(seconds=_deadline_s(run, registry)) + _STALE_GRACE:
        return
    session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run.id, WorkflowRun.status.in_(("queued", "running")))
        .values(
            status="failed",
            finished_at=func.now(),
            error={"kind": "interrupted", "message": "The run did not finish. Start a new run to try again."},
        )
    )
    session.commit()
    session.refresh(run)


# --------------------------------------------------------------------------- skills


def list_skills(session: Session, principal: Principal, project_id: uuid.UUID, registry: SkillRegistry) -> SkillList:
    project = service.find_project(session, principal, project_id)
    spec = service.current_spec(session, project)
    items = []
    for m in registry.manifests():
        missing = unmet_preconditions(m, spec)
        items.append(
            SkillInfo(
                id=m.id,
                name=m.name,
                description=m.description,
                category=m.category.value,
                version=m.version,
                applicable=not missing,
                unmet_preconditions=missing,
                message_required="message" in m.required_inputs,
            )
        )
    return SkillList(items=items)


# --------------------------------------------------------------------------- create


def create_run(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID,
    body: RunCreate,
    idempotency_key: str | None,
    runtime: ModelRuntime | None,
    registry: SkillRegistry,
) -> tuple[RunOut, bool]:
    """Create a queued run. Returns (run, created). The caller schedules execution when created."""
    project = service.find_project(session, principal, project_id)
    fingerprint = None
    if idempotency_key is not None:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise InvalidRequest("Idempotency-Key must be 8-128 characters of [A-Za-z0-9._:-].")
        fingerprint = "sha256:" + hashlib.sha256(f"{project_id}:{body.model_dump_json()}".encode()).hexdigest()
        existing = session.scalars(
            select(WorkflowRun).where(
                WorkflowRun.tenant_id == principal.tenant_id, WorkflowRun.idempotency_key == idempotency_key
            )
        ).one_or_none()
        if existing is not None:
            if existing.idempotency_fingerprint != fingerprint:
                raise IdempotencyConflict("This Idempotency-Key was already used with a different request.")
            return _run_out(existing), False

    spec = service.current_spec(session, project)
    skill_version = None
    if body.skill_id is not None:
        try:
            skill_version = SkillRouter(registry).check_explicit(body.skill_id, spec).version
        except RoutingError as exc:
            raise SkillNotApplicable(str(exc)) from exc

    if runtime is None:
        raise ModelNotConfigured(
            "Set MODEL_PROFILE and MODEL_ID (see .env.example and docs/adr/0007-model-providers.md)."
        )
    try:
        check_data_policy(
            runtime.capabilities, _classification(spec), allow_remote=runtime.allow_remote_for_confidential
        )
    except ModelError as exc:
        raise ModelPolicyDenied(exc.detail) from exc

    active = session.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.tenant_id == principal.tenant_id, WorkflowRun.status.in_(("queued", "running")))
    )
    if (active or 0) >= MAX_ACTIVE_RUNS_PER_TENANT:
        raise TooManyRuns(f"At most {MAX_ACTIVE_RUNS_PER_TENANT} AI runs may be active at once. Try again shortly.")

    run = WorkflowRun(
        id=uuid.uuid4(),
        tenant_id=principal.tenant_id,
        project_id=project.id,
        skill_id=body.skill_id,
        skill_version=skill_version,
        status="queued",
        input={"message": body.message},
        base_revision=project.current_revision,
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
    )
    session.add(run)
    service.audit(
        session,
        principal,
        project.id,
        "ai.run.started",
        run_id=str(run.id),
        skill=f"{body.skill_id}@{skill_version}" if body.skill_id else "auto",
        model=runtime.label,
        message_chars=len(body.message),
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise IdempotencyConflict("A concurrent request used the same Idempotency-Key.") from None
    session.refresh(run)
    return _run_out(run), True


# --------------------------------------------------------------------------- execute


def _failed_model_info(runtime: ModelRuntime, prompt_version: str | None, exc: ModelError) -> dict[str, Any]:
    return {
        "model_id": runtime.model_id,
        "profile": runtime.profile,
        "prompt_version": prompt_version,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "repaired": False,
        "calls": [c.model_dump() for c in exc.calls],
    }


def execute_run(db: Database, run_id: uuid.UUID, runtime: ModelRuntime, registry: SkillRegistry) -> None:
    """Route and run a queued request to completion. Safe to call more than once (claims atomically)."""
    session = db.new_session()
    try:
        claimed = session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status == "queued")
            .values(status="running", started_at=func.now())
            .returning(WorkflowRun.id)
        ).first()
        session.commit()
        if claimed is None:
            return
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        principal = Principal(tenant_id=run.tenant_id, user_id=run.created_by)
        project = service.find_project(session, principal, run.project_id)
        spec = service.spec_at(session, project, run.base_revision)
        message = _message(run)

        status = "failed"
        result: dict[str, Any] | None = None
        model: dict[str, Any] | None = None
        error: dict[str, Any] | None = None
        prompt_version: str | None = None
        try:
            check_data_policy(
                runtime.capabilities, _classification(spec), allow_remote=runtime.allow_remote_for_confidential
            )
            provider = runtime.factory()
            decision = SkillRouter(registry).route(
                message,
                spec,
                provider=provider,
                budget=Budget(max_calls=2, max_total_tokens=8_000, deadline_s=ROUTING_DEADLINE_S),
                explicit=run.skill_id,
                call_timeout_s=min(runtime.call_timeout_s, ROUTING_DEADLINE_S),
                prices=runtime.prices,
            )
            run.routing = decision.model_dump(mode="json")
            if decision.skill_id is None:
                status = "succeeded"
                result = {
                    "summary": "No skill fits this request.",
                    "not_applicable_reason": decision.rationale,
                    "proposals": [],
                }
            else:
                skill = registry.get(decision.skill_id)
                manifest = skill.manifest
                prompt_version = manifest.prompt_version
                run.skill_id, run.skill_version = manifest.id, manifest.version
                context = SkillContext(
                    spec=spec,
                    provider=provider,
                    budget=Budget(
                        max_calls=max(1, manifest.max_model_calls),
                        max_total_tokens=max(1, manifest.max_total_tokens),
                        deadline_s=manifest.timeout_s,
                    ),
                    prices=runtime.prices,
                    call_timeout_s=runtime.call_timeout_s,
                )
                output = skill.run(context, dict(run.input))
                status = "succeeded"
                result = {
                    "summary": output.summary,
                    "not_applicable_reason": output.not_applicable_reason,
                    "proposals": [p.model_dump(mode="json") for p in output.proposals],
                }
                model = output.model
        except ModelError as exc:
            error = {"kind": exc.kind.value, "message": exc.user_message}
            model = _failed_model_info(runtime, prompt_version, exc)
            log.warning("ai run failed", extra={"run_id": str(run_id), "kind": exc.kind.value, "detail": exc.detail})
        except (ValueError, RoutingError) as exc:
            error = {"kind": "invalid_input", "message": str(exc)[:300]}
        except Exception:
            log.exception("ai run crashed", extra={"run_id": str(run_id)})
            error = {"kind": "internal", "message": "The run failed unexpectedly. Quote the run id when reporting it."}

        run.status = status
        run.result = result
        run.model = model
        run.error = error
        run.finished_at = datetime.now(UTC)
        service.audit(
            session,
            principal,
            project.id,
            "ai.run.succeeded" if status == "succeeded" else "ai.run.failed",
            run_id=str(run_id),
            skill=run.skill_id,
            routing=(run.routing or {}).get("method"),
            proposals=len(result["proposals"]) if result else 0,
            error_kind=error["kind"] if error else None,
        )
        session.commit()
    finally:
        session.close()


# --------------------------------------------------------------------------- read


def get_run(
    session: Session, principal: Principal, project_id: uuid.UUID, run_id: uuid.UUID, registry: SkillRegistry
) -> RunOut:
    service.find_project(session, principal, project_id)
    run = _run(session, principal, project_id, run_id)
    _expire_if_stale(session, run, registry)
    return _run_out(run)


def list_runs(session: Session, principal: Principal, project_id: uuid.UUID, registry: SkillRegistry) -> RunPage:
    service.find_project(session, principal, project_id)
    rows = list(
        session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.tenant_id == principal.tenant_id, WorkflowRun.project_id == project_id)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(20)
        )
    )
    for run in rows:
        _expire_if_stale(session, run, registry)
    return RunPage(items=[_run_out(r) for r in rows])


# --------------------------------------------------------------------------- apply


def apply_run(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    if_match: str | None,
    body: ApplyRunRequest,
) -> ApplyRunResult:
    project = service.lock_project_at_revision(session, principal, project_id, if_match)
    run = _run(session, principal, project_id, run_id, lock=True)
    if run.applied_revision is not None or run.decisions is not None:
        raise RunAlreadyApplied("Start a new run to propose further changes.")
    if run.status != "succeeded" or not run.skill_id or not (run.result or {}).get("proposals"):
        raise RunNotApplicable(f"Run status is '{run.status}' and it has no proposals.")

    commands = _COMMANDS.validate_python(run.result["proposals"] if run.result else [])
    known = {c.proposal_id for c in commands}
    decisions: dict[str, Decision] = {}
    errors = []
    for i, item in enumerate(body.decisions):
        if item.proposal_id not in known:
            errors.append(FieldError(path=f"/decisions/{i}/proposal_id", message="unknown proposal id"))
        elif item.proposal_id in decisions:
            errors.append(FieldError(path=f"/decisions/{i}/proposal_id", message="duplicate decision"))
        else:
            decisions[item.proposal_id] = item.decision
    if errors:
        raise SpecInvalid("Some decisions do not match this run's proposals.", errors=errors)

    model = run.model or {}
    provenance = Provenance(
        source=Source.MODEL,
        skill_id=run.skill_id,
        skill_version=run.skill_version,
        model_id=f"{model.get('profile', 'unknown')}:{model.get('model_id', 'unknown')}"[:200],
        prompt_version=model.get("prompt_version"),
    )
    spec = service.current_spec(session, project)
    updated, results = apply_commands(spec, commands, decisions, provenance=provenance, actor=principal.user_id)
    applied = sum(1 for r in results if r.outcome is Outcome.APPLIED)
    confirmed = sum(
        1 for r in results if r.outcome is Outcome.APPLIED and decisions.get(r.proposal_id) is Decision.CONFIRM
    )
    summary = body.change_summary or f"Applied {applied} AI proposal(s) from {run.skill_id}"
    outcome = service.write_revision(
        session,
        principal,
        project,
        updated,
        summary,
        audit_action="ai.proposals.applied",
        audit_details={"run_id": str(run.id), "applied": applied, "confirmed": confirmed, "decided": len(decisions)},
    )
    run.decisions = {pid: d.value for pid, d in decisions.items()}
    run.applied_revision = outcome.revision.revision if outcome.created else None
    session.commit()
    session.refresh(run)
    return ApplyRunResult(
        run=_run_out(run), results=results, revision=outcome.revision, revision_created=outcome.created
    )
