"""Authentication boundary.

Milestone 1 ships only ``AUTH_MODE=dev``: identity comes from the
``X-Dev-Tenant`` and ``X-Dev-User`` headers. This is explicitly *not* secure
and is refused at startup when ``APP_ENV=production`` (see ``config.py``).

Everything downstream depends only on :class:`Principal`, so replacing this
module with an OIDC/JWT verifier does not touch the service layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header

from .errors import Unauthenticated

_TENANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    user_id: str


def dev_principal(
    x_dev_tenant: Annotated[str | None, Header(description="Development only: tenant identifier.")] = None,
    x_dev_user: Annotated[str | None, Header(description="Development only: user identifier.")] = None,
) -> Principal:
    if not x_dev_tenant or not x_dev_user:
        raise Unauthenticated("Send X-Dev-Tenant and X-Dev-User headers (development auth mode).")
    if not _TENANT.fullmatch(x_dev_tenant):
        raise Unauthenticated("X-Dev-Tenant must be lowercase letters, digits and hyphens (max 63).")
    if not _USER.fullmatch(x_dev_user):
        raise Unauthenticated("X-Dev-User contains unsupported characters.")
    return Principal(tenant_id=x_dev_tenant, user_id=x_dev_user)


CurrentPrincipal = Annotated[Principal, Depends(dev_principal)]
