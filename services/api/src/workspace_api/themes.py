"""Organization brand themes: storage and admin updates (Milestone 7).

Themes live next to the policy set in ``org_settings``, versioned separately. Only
``org-admin`` principals change them, with ``If-Match: "vN"``; every change is audited. A
specification selects a theme with ``design_system.id = "org:<theme id>"``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from design_system import BrandThemeSet
from org_policy import PolicySet

from . import service
from .auth import Principal
from .db import OrgSettings
from .errors import Forbidden, PreconditionRequired, RevisionConflict
from .schemas import OrgThemesOut

_VERSION_ETAG = re.compile(r'^"v(\d{1,9})"$')


def themes_for(session: Session, tenant_id: str) -> BrandThemeSet:
    row = session.scalar(select(OrgSettings).where(OrgSettings.tenant_id == tenant_id))
    return BrandThemeSet.model_validate({"items": row.themes}) if row is not None else BrandThemeSet()


def get_themes(session: Session, principal: Principal) -> OrgThemesOut:
    row = session.scalar(select(OrgSettings).where(OrgSettings.tenant_id == principal.tenant_id))
    if row is None:
        return OrgThemesOut(version=0, themes=BrandThemeSet())
    return OrgThemesOut(version=row.themes_version, themes=BrandThemeSet.model_validate({"items": row.themes}))


def put_themes(session: Session, principal: Principal, if_match: str | None, themes: BrandThemeSet) -> OrgThemesOut:
    if not principal.has_role("org-admin"):
        raise Forbidden("Only organization admins (role 'org-admin') can change brand themes.")
    if if_match is None:
        raise PreconditionRequired('Send If-Match with the themes version you edited, e.g. If-Match: "v3".')
    match = _VERSION_ETAG.fullmatch(if_match.strip())
    if match is None:
        raise RevisionConflict('If-Match must be a version such as "v3".')
    row = session.scalar(select(OrgSettings).where(OrgSettings.tenant_id == principal.tenant_id).with_for_update())
    current = row.themes_version if row is not None else 0
    if int(match.group(1)) != current:
        raise RevisionConflict(
            f"The brand themes changed since you loaded them (now v{current}). Reload and try again."
        )
    items = themes.model_dump(mode="json")["items"]
    if row is None:
        row = OrgSettings(
            tenant_id=principal.tenant_id,
            policies=PolicySet().model_dump(mode="json"),
            policies_version=0,
            themes=items,
            themes_version=1,
            updated_by=principal.user_id,
        )
        session.add(row)
    else:
        row.themes = items
        row.themes_version = current + 1
        row.updated_by = principal.user_id
        row.updated_at = datetime.now(UTC)
    service.audit(
        session, principal, None, "org.themes.updated", version=current + 1, themes=[t.id for t in themes.items]
    )
    session.commit()
    return get_themes(session, principal)
