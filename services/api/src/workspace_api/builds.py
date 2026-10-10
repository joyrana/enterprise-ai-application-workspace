"""Isolated builds of generated projects (ADR-0015).

The API process only records build requests. A separate worker (``python -m
workspace_api.build_worker``) claims queued builds, generates the project archive, runs it
through ``build_runner`` (verification, then a locked-down container) and stores the report.
The API never starts a container or executes generated code.

Bounds: one active build per project; a build that stays ``running`` past the runner deadline
plus a grace period (for example because a worker crashed) is marked ``runner_error``.
"""

from __future__ import annotations

import json
import socket
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from build_runner import BuildReport, SandboxLimits, build_archive
from codegen_react import toolchain

from . import code, service
from .auth import Principal
from .db import BUILD_ACTIVE, Build, Database
from .errors import BuildAlreadyActive, NotFound
from .schemas import BuildOut, BuildPage, BuildReportOut

DEFAULT_LIMITS = SandboxLimits()
STALE_GRACE = timedelta(minutes=5)

#: (archive path, output dir, toolchain, image, limits) -> report. Injected in tests.
Builder = Callable[[Path, Path, dict[str, Any], str, SandboxLimits], BuildReport]


def _default_builder(
    archive: Path, output: Path, tools: dict[str, Any], image: str, limits: SandboxLimits
) -> BuildReport:
    return build_archive(archive, output, tools, image=image, limits=limits)


def _out(build: Build) -> BuildOut:
    report = None
    if build.report:
        raw = build.report
        report = BuildReportOut(
            image=str(raw.get("image", "")),
            duration_ms=int(raw.get("duration_ms", 0)),
            exit_code=raw.get("exit_code"),
            reason=raw.get("reason"),
            steps=raw.get("steps", []),
            log_tail=raw.get("log_tail", []),
            artifacts=raw.get("artifacts", {}),
            isolation=raw.get("isolation", []),
        )
    return BuildOut(
        id=build.id,
        spec_revision=build.spec_revision,
        generator=build.generator,
        status=build.status,
        requested_by=build.requested_by,
        created_at=build.created_at,
        started_at=build.started_at,
        finished_at=build.finished_at,
        report=report,
    )


def request_build(session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None) -> BuildOut:
    """Queue a build. Refused while generation is blocked or another build of the project is active."""
    project = service.find_project(session, principal, project_id, lock=True)
    number, generated = code.project_at(session, principal, project_id, revision)
    active = session.scalar(
        select(func.count())
        .select_from(Build)
        .where(Build.tenant_id == principal.tenant_id, Build.project_id == project.id, Build.status.in_(BUILD_ACTIVE))
    )
    if active:
        raise BuildAlreadyActive("Wait for the current build to finish before starting another.")
    build = Build(
        tenant_id=principal.tenant_id,
        project_id=project.id,
        spec_revision=number,
        generator=generated.generator,
        status="queued",
        requested_by=principal.user_id,
    )
    session.add(build)
    session.flush()
    service.audit(session, principal, project.id, "build.requested", build_id=str(build.id), spec_revision=number)
    session.commit()
    session.refresh(build)
    return _out(build)


def list_builds(session: Session, principal: Principal, project_id: uuid.UUID) -> BuildPage:
    project = service.find_project(session, principal, project_id)
    rows = session.scalars(
        select(Build)
        .where(Build.tenant_id == principal.tenant_id, Build.project_id == project.id)
        .order_by(Build.created_at.desc(), Build.id)
        .limit(20)
    ).all()
    return BuildPage(items=[_out(b) for b in rows])


def get_build(session: Session, principal: Principal, project_id: uuid.UUID, build_id: uuid.UUID) -> BuildOut:
    project = service.find_project(session, principal, project_id)
    build = session.scalar(
        select(Build).where(
            Build.id == build_id, Build.tenant_id == principal.tenant_id, Build.project_id == project.id
        )
    )
    if build is None:
        raise NotFound("No such build in this project.")
    return _out(build)


# --------------------------------------------------------------------------- worker side


def recover_stale(session: Session, limits: SandboxLimits = DEFAULT_LIMITS) -> int:
    """Mark builds stuck in ``running`` (crashed worker) as ``runner_error``. Returns how many."""
    cutoff = datetime.now(UTC) - timedelta(seconds=limits.timeout_s) - STALE_GRACE
    result = session.execute(
        update(Build)
        .where(Build.status == "running", Build.started_at < cutoff)
        .values(
            status="runner_error",
            finished_at=func.now(),
            report={"image": "", "duration_ms": 0, "exit_code": None, "reason": "the worker stopped responding"},
        )
        .returning(Build.id)
    ).all()
    session.commit()
    return len(result)


def claim_next(session: Session, worker: str) -> Build | None:
    """Atomically take the oldest queued build (safe with several workers: ``SKIP LOCKED``)."""
    build = session.scalar(
        select(Build)
        .where(Build.status == "queued")
        .order_by(Build.created_at, Build.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if build is None:
        session.commit()
        return None
    build.status = "running"
    build.started_at = datetime.now(UTC)
    build.worker = worker[:128]
    session.commit()
    return build


def process_one(
    db: Database,
    image: str,
    limits: SandboxLimits = DEFAULT_LIMITS,
    builder: Builder = _default_builder,
    worker: str | None = None,
) -> uuid.UUID | None:
    """Claim one queued build, run it in the isolated runner and store the report."""
    session = db.new_session()
    try:
        recover_stale(session, limits)
        build = claim_next(session, worker or socket.gethostname())
        if build is None:
            return None
        principal = Principal(tenant_id=build.tenant_id, user_id=build.requested_by)
        try:
            number, generated = code.project_at(session, principal, build.project_id, build.spec_revision)
            project = service.find_project(session, principal, build.project_id)
            filename, data = code.archive_bytes(project.name, number, generated)
            with tempfile.TemporaryDirectory(prefix="workspace-build-") as tmp:
                archive = Path(tmp) / filename
                archive.write_bytes(data)
                report = builder(archive, Path(tmp) / "dist", toolchain(), image, limits)
            result: dict[str, Any] = json_report(report)
            status = report.status
        except Exception as exc:  # any failure must end the build; it must never stay "running"
            result = {
                "image": image,
                "duration_ms": 0,
                "exit_code": None,
                "reason": f"worker error: {type(exc).__name__}",
            }
            status = "runner_error"
        build.status = status
        build.report = result
        build.finished_at = datetime.now(UTC)
        service.audit(session, principal, build.project_id, "build.finished", build_id=str(build.id), status=status)
        session.commit()
        return build.id
    finally:
        session.close()


def json_report(report: BuildReport) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(report.to_json())
    return data
