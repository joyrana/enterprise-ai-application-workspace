"""Organization policies (ADR-0018): storage, admin updates and enforcement.

The policy set is per tenant, versioned, and changed only by principals with the
``org-admin`` role, using ``If-Match: "vN"`` so concurrent edits never silently overwrite each
other. Every change is audited. ``error`` findings block code generation, builds and
upgrades for the tenant's projects, the same way UI errors do.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from appspec import ApplicationSpec
from design_system import derive_document
from org_policy import PolicyFinding, PolicySet, blocking, evaluate

from . import service, ui
from .auth import Principal
from .db import OrgSettings
from .errors import AppError, FieldError, Forbidden, PreconditionRequired, RevisionConflict
from .schemas import OrgPolicyOut, PolicyReport

_VERSION_ETAG = re.compile(r'^"v(\d{1,9})"$')


class PolicyBlocked(AppError):
    status, code, title = 422, "policy-blocked", "Organization policy blocks code generation for this revision"


def _row(session: Session, tenant_id: str, *, lock: bool = False) -> OrgSettings | None:
    stmt = select(OrgSettings).where(OrgSettings.tenant_id == tenant_id)
    if lock:
        stmt = stmt.with_for_update()
    return session.scalar(stmt)


def policy_for(session: Session, tenant_id: str) -> tuple[int, PolicySet]:
    row = _row(session, tenant_id)
    if row is None:
        return 0, PolicySet()
    return row.policies_version, PolicySet.model_validate(row.policies)


def get_policies(session: Session, principal: Principal) -> OrgPolicyOut:
    row = _row(session, principal.tenant_id)
    if row is None:
        return OrgPolicyOut(version=0, policy=PolicySet(), updated_by=None, updated_at=None)
    return OrgPolicyOut(
        version=row.policies_version,
        policy=PolicySet.model_validate(row.policies),
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def put_policies(session: Session, principal: Principal, if_match: str | None, policy: PolicySet) -> OrgPolicyOut:
    if not principal.has_role("org-admin"):
        raise Forbidden("Only organization admins (role 'org-admin') can change organization policies.")
    if if_match is None:
        raise PreconditionRequired('Send If-Match with the policy version you edited, e.g. If-Match: "v3".')
    match = _VERSION_ETAG.fullmatch(if_match.strip())
    if match is None:
        raise RevisionConflict('If-Match must be a policy version such as "v3".')
    expected = int(match.group(1))
    row = _row(session, principal.tenant_id, lock=True)
    current = row.policies_version if row is not None else 0
    if expected != current:
        raise RevisionConflict(f"The policies changed since you loaded them (now v{current}). Reload and try again.")
    document = policy.model_dump(mode="json")
    if row is None:
        row = OrgSettings(
            tenant_id=principal.tenant_id, policies=document, policies_version=1, updated_by=principal.user_id
        )
        session.add(row)
    else:
        row.policies = document
        row.policies_version = current + 1
        row.updated_by = principal.user_id
        row.updated_at = datetime.now(UTC)
    service.audit(
        session,
        principal,
        None,
        "org.policies.updated",
        version=current + 1,
        rules=[r.id for r in policy.rules],
    )
    session.commit()
    session.refresh(row)
    return get_policies(session, principal)


def findings_for(
    session: Session, tenant_id: str, spec: ApplicationSpec, revision: int | None
) -> tuple[int, str, list[PolicyFinding]]:
    version, policy = policy_for(session, tenant_id)
    contract, _ = ui.choose(spec)
    if not policy.rules:
        return version, contract.id, []
    document = derive_document(spec, spec_revision=revision)
    return version, contract.id, evaluate(policy, spec, document, contract.id)


def enforce(session: Session, tenant_id: str, spec: ApplicationSpec, revision: int) -> None:
    """Raise ``PolicyBlocked`` when the tenant's policies have error findings for this revision."""
    version, _, findings = findings_for(session, tenant_id, spec, revision)
    errors = blocking(findings)
    if errors:
        raise PolicyBlocked(
            f"Revision r{revision} breaks {len(errors)} organization policy rule(s) (policy v{version}).",
            errors=[FieldError(path=f.path, message=f.message, code=f.rule_id) for f in errors],
        )


def report(session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None) -> PolicyReport:
    project = service.find_project(session, principal, project_id)
    number = project.current_revision if revision is None else revision
    spec = service.spec_at(session, project, number)
    version, design_system, findings = findings_for(session, principal.tenant_id, spec, number)
    return PolicyReport(
        policy_version=version,
        spec_revision=number,
        design_system=design_system,
        findings=findings,
        blocked=bool(blocking(findings)),
    )
