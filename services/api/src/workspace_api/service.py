"""Project and specification use cases.

All functions take an explicit :class:`Principal` and scope every query by its
tenant. A project in another tenant is indistinguishable from a missing one
(404), so identifiers cannot be probed across tenants.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from appspec import (
    ApplicationSpec,
    Severity,
    ValidationIssue,
    content_hash,
    load_spec,
    semantic_fingerprint,
    stamp_revisions,
    summarize,
    validate_spec,
)
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import Principal
from .db import AuditEvent, Project, SpecRevision
from .errors import (
    AppError,
    FieldError,
    IdempotencyConflict,
    NotFound,
    PreconditionRequired,
    RevisionConflict,
    SpecInvalid,
)
from .schemas import (
    AuditEventOut,
    AuditPage,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    SpecRevisionMeta,
    SpecRevisionOut,
    SpecRevisionPage,
    SpecUpdate,
    SpecValidationResult,
)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_ETAG = re.compile(r'^(?:W/)?"r([1-9][0-9]{0,9})"$')


class InvalidRequest(AppError):
    status, code, title = 400, "invalid-request", "Invalid request"


# --------------------------------------------------------------------------- helpers


def etag(revision: int) -> str:
    return f'"r{revision}"'


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise PreconditionRequired("Send If-Match with the ETag of the revision you edited, e.g. If-Match: \"r3\".")
    match = _ETAG.fullmatch(value.strip())
    if match is None:
        raise RevisionConflict("If-Match must be a single revision ETag such as \"r3\".")
    return int(match.group(1))


def _encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidRequest("Malformed pagination cursor.") from exc
    if not isinstance(data, dict):
        raise InvalidRequest("Malformed pagination cursor.")
    return data


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        current_revision=p.current_revision,
        created_by=p.created_by,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _warnings(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.severity is Severity.WARNING]


def _revision_out(row: SpecRevision) -> SpecRevisionOut:
    spec = load_spec(row.document)
    return SpecRevisionOut(
        project_id=row.project_id,
        revision=row.revision,
        schema_version=row.schema_version,
        content_hash=row.content_hash,
        change_summary=row.change_summary,
        created_by=row.created_by,
        created_at=row.created_at,
        spec=spec,
        summary=summarize(spec),
        issues=_warnings(validate_spec(spec)),
    )


def _audit(session: Session, principal: Principal, project_id: uuid.UUID | None, action: str, **details: Any) -> None:
    session.add(
        AuditEvent(
            tenant_id=principal.tenant_id, project_id=project_id, actor=principal.user_id, action=action, details=details
        )
    )


def _project(session: Session, principal: Principal, project_id: uuid.UUID, *, lock: bool = False) -> Project:
    stmt = select(Project).where(Project.id == project_id, Project.tenant_id == principal.tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    project = session.scalars(stmt).one_or_none()
    if project is None:
        raise NotFound(f"Project {project_id} was not found.")
    return project


def _revision_row(session: Session, project: Project, revision: int) -> SpecRevision:
    row = session.get(SpecRevision, (project.id, revision))
    if row is None:
        raise NotFound(f"Revision {revision} of project {project.id} was not found.")
    return row


def _new_revision(
    project_id: uuid.UUID, revision: int, spec: ApplicationSpec, actor: str, change_summary: str | None
) -> SpecRevision:
    return SpecRevision(
        project_id=project_id,
        revision=revision,
        schema_version=spec.schema_version,
        document=spec.model_dump(mode="json"),
        content_hash=content_hash(spec),
        semantic_hash=semantic_fingerprint(spec),
        change_summary=change_summary,
        created_by=actor,
    )


# --------------------------------------------------------------------------- projects


@dataclass(frozen=True)
class CreateResult:
    project: ProjectOut
    created: bool


def create_project(
    session: Session, principal: Principal, data: ProjectCreate, idempotency_key: str | None
) -> CreateResult:
    fingerprint = None
    if idempotency_key is not None:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise InvalidRequest("Idempotency-Key must be 8-128 characters of [A-Za-z0-9._:-].")
        fingerprint = "sha256:" + hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        existing = _by_idempotency_key(session, principal, idempotency_key)
        if existing is not None:
            return _replay(existing, fingerprint)

    project_id = uuid.uuid4()
    spec = stamp_revisions(None, ApplicationSpec.empty(data.name, data.description), 1)
    project = Project(
        id=project_id,
        tenant_id=principal.tenant_id,
        name=data.name,
        description=data.description,
        current_revision=1,
        created_by=principal.user_id,
        idempotency_key=idempotency_key,
        idempotency_fingerprint=fingerprint,
    )
    session.add(project)
    session.flush()
    session.add(_new_revision(project_id, 1, spec, principal.user_id, "Project created"))
    _audit(session, principal, project_id, "project.created", name=data.name, revision=1)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request with the same Idempotency-Key won the race.
        session.rollback()
        if idempotency_key is None or fingerprint is None:
            raise
        existing = _by_idempotency_key(session, principal, idempotency_key)
        if existing is None:
            raise
        return _replay(existing, fingerprint)
    session.refresh(project)
    return CreateResult(_project_out(project), created=True)


def _by_idempotency_key(session: Session, principal: Principal, key: str) -> Project | None:
    return session.scalars(
        select(Project).where(Project.tenant_id == principal.tenant_id, Project.idempotency_key == key)
    ).one_or_none()


def _replay(existing: Project, fingerprint: str) -> CreateResult:
    if existing.idempotency_fingerprint != fingerprint:
        raise IdempotencyConflict("This Idempotency-Key was already used with a different request body.")
    return CreateResult(_project_out(existing), created=False)


def list_projects(session: Session, principal: Principal, limit: int, cursor: str | None) -> ProjectPage:
    stmt = select(Project).where(Project.tenant_id == principal.tenant_id)
    if cursor:
        data = _decode_cursor(cursor)
        try:
            at = datetime.fromisoformat(str(data["at"]))
            pid = uuid.UUID(str(data["id"]))
        except (KeyError, ValueError) as exc:
            raise InvalidRequest("Malformed pagination cursor.") from exc
        stmt = stmt.where(tuple_(Project.created_at, Project.id) < tuple_(at, pid))
    rows = list(session.scalars(stmt.order_by(Project.created_at.desc(), Project.id.desc()).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor({"at": last.created_at.isoformat(), "id": str(last.id)})
        rows = rows[:limit]
    return ProjectPage(items=[_project_out(p) for p in rows], next_cursor=next_cursor)


def get_project(session: Session, principal: Principal, project_id: uuid.UUID) -> ProjectOut:
    return _project_out(_project(session, principal, project_id))


# --------------------------------------------------------------------------- specification


def get_spec(
    session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None = None
) -> SpecRevisionOut:
    project = _project(session, principal, project_id)
    return _revision_out(_revision_row(session, project, revision or project.current_revision))


def validate_candidate(session: Session, principal: Principal, project_id: uuid.UUID, spec: ApplicationSpec) -> SpecValidationResult:
    _project(session, principal, project_id)
    issues = validate_spec(spec)
    return SpecValidationResult(
        valid=not any(i.severity is Severity.ERROR for i in issues), issues=issues, summary=summarize(spec)
    )


@dataclass(frozen=True)
class UpdateResult:
    revision: SpecRevisionOut
    created: bool


def update_spec(
    session: Session, principal: Principal, project_id: uuid.UUID, if_match: str | None, update: SpecUpdate
) -> UpdateResult:
    expected = parse_if_match(if_match)
    project = _project(session, principal, project_id, lock=True)
    if expected != project.current_revision:
        raise RevisionConflict(
            f"You edited revision {expected}, but the current revision is {project.current_revision}. "
            "Reload, re-apply your change, and save again.",
            current_revision=project.current_revision,
        )

    issues = validate_spec(update.spec)
    errors = [i for i in issues if i.severity is Severity.ERROR]
    if errors:
        raise SpecInvalid(
            f"{len(errors)} reference error(s) must be fixed before saving.",
            errors=[FieldError(path=i.path, message=i.message, code=i.code) for i in errors],
        )

    current = _revision_row(session, project, project.current_revision)
    if semantic_fingerprint(update.spec) == current.semantic_hash:
        # Nothing changed: no new revision. The request-scoped session ends the transaction (and the lock).
        return UpdateResult(_revision_out(current), created=False)

    new_revision = project.current_revision + 1
    stamped = stamp_revisions(load_spec(current.document), update.spec, new_revision)
    row = _new_revision(project.id, new_revision, stamped, principal.user_id, update.change_summary)
    session.add(row)
    project.current_revision = new_revision
    project.name = stamped.metadata.name
    project.description = stamped.metadata.description
    project.updated_at = datetime.now(UTC)
    _audit(
        session,
        principal,
        project.id,
        "spec.revised",
        revision=new_revision,
        content_hash=row.content_hash,
        change_summary=update.change_summary,
        warnings=len(issues),
    )
    session.commit()
    session.refresh(row)
    return UpdateResult(_revision_out(row), created=True)


def list_revisions(
    session: Session, principal: Principal, project_id: uuid.UUID, limit: int, cursor: str | None
) -> SpecRevisionPage:
    project = _project(session, principal, project_id)
    stmt = select(SpecRevision).where(SpecRevision.project_id == project.id)
    if cursor:
        before = _decode_cursor(cursor).get("before")
        if not isinstance(before, int):
            raise InvalidRequest("Malformed pagination cursor.")
        stmt = stmt.where(SpecRevision.revision < before)
    rows = list(session.scalars(stmt.order_by(SpecRevision.revision.desc()).limit(limit + 1)))
    next_cursor = _encode_cursor({"before": rows[limit - 1].revision}) if len(rows) > limit else None
    return SpecRevisionPage(
        items=[
            SpecRevisionMeta(
                revision=r.revision,
                schema_version=r.schema_version,
                content_hash=r.content_hash,
                change_summary=r.change_summary,
                created_by=r.created_by,
                created_at=r.created_at,
            )
            for r in rows[:limit]
        ],
        next_cursor=next_cursor,
    )


def list_audit(
    session: Session, principal: Principal, project_id: uuid.UUID, limit: int, cursor: str | None
) -> AuditPage:
    project = _project(session, principal, project_id)
    stmt = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id, AuditEvent.project_id == project.id)
    if cursor:
        before = _decode_cursor(cursor).get("before")
        if not isinstance(before, int):
            raise InvalidRequest("Malformed pagination cursor.")
        stmt = stmt.where(AuditEvent.id < before)
    rows = list(session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(limit + 1)))
    next_cursor = _encode_cursor({"before": rows[limit - 1].id}) if len(rows) > limit else None
    return AuditPage(
        items=[
            AuditEventOut(id=e.id, actor=e.actor, action=e.action, occurred_at=e.occurred_at, details=e.details)
            for e in rows[:limit]
        ],
        next_cursor=next_cursor,
    )
