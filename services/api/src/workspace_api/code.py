"""Generated code: manifest, files, diffs between revisions and zip downloads (ADR-0014).

Code is generated on request from a spec revision; nothing is stored and the
generated code is never executed by the API. Generation is refused while the
UI IR has errors.
"""

from __future__ import annotations

import io
import uuid
import zipfile

from sqlalchemy.orm import Session

from codegen_react import GeneratedProject, GenerationBlocked, diff_projects, generate_project, package_name

from . import service, ui
from .auth import Principal
from .errors import AppError, FieldError, NotFound
from .schemas import CodeDiff, CodeFile, CodeFileInfo, CodeManifest

_ZIP_TIME = (2026, 1, 1, 0, 0, 0)  # fixed, so the same revision always yields the same archive


class CodeGenerationBlocked(AppError):
    status, code, title = 422, "code-generation-blocked", "The screens have errors that block code generation"


def _language(path: str) -> str:
    return {"tsx": "tsx", "ts": "typescript", "json": "json", "md": "markdown", "html": "html"}.get(
        path.rsplit(".", 1)[-1], "text"
    )


def project_at(
    session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None
) -> tuple[int, GeneratedProject]:
    project = service.find_project(session, principal, project_id)
    number = project.current_revision if revision is None else revision
    spec = service.spec_at(session, project, number)
    contract, _ = ui.choose(spec)
    try:
        return number, generate_project(spec, contract, spec_revision=number)
    except GenerationBlocked as exc:
        raise CodeGenerationBlocked(
            f"Revision r{number} has {len(exc.issues)} UI error(s); fix them in the specification first.",
            errors=[FieldError(path=i.path, message=i.message, code=i.code) for i in exc.issues],
        ) from exc


def manifest(session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None) -> CodeManifest:
    number, generated = project_at(session, principal, project_id, revision)
    return CodeManifest(
        spec_revision=number,
        generator=generated.generator,
        design_system=generated.design_system,
        files=[
            CodeFileInfo(path=p, bytes=len(c.encode("utf-8")), sha256=generated.sha256(p), language=_language(p))
            for p, c in generated.files.items()
        ],
        warnings=generated.warnings,
    )


def file(session: Session, principal: Principal, project_id: uuid.UUID, path: str, revision: int | None) -> CodeFile:
    number, generated = project_at(session, principal, project_id, revision)
    if path not in generated.files:
        raise NotFound(f"r{number} has no generated file '{path}'.")
    return CodeFile(
        path=path,
        spec_revision=number,
        language=_language(path),
        sha256=generated.sha256(path),
        content=generated.files[path],
    )


def diff(session: Session, principal: Principal, project_id: uuid.UUID, base: int, head: int | None) -> CodeDiff:
    base_number, before = project_at(session, principal, project_id, base)
    head_number, after = project_at(session, principal, project_id, head)
    return CodeDiff(from_revision=base_number, to_revision=head_number, files=diff_projects(before, after))


def archive_bytes(project_name: str, number: int, generated: GeneratedProject) -> tuple[str, bytes]:
    """The deterministic zip of a generated project (also what the build worker hands the runner)."""
    root = f"{package_name(project_name)}-r{number}"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in generated.files.items():
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=_ZIP_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content.encode("utf-8"))
    return f"{root}.zip", buffer.getvalue()


def archive(session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None) -> tuple[str, bytes]:
    number, generated = project_at(session, principal, project_id, revision)
    project = service.find_project(session, principal, project_id)
    return archive_bytes(project.name, number, generated)
