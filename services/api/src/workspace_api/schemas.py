"""Request and response contracts for API v1.

The spec itself is typed as :class:`appspec.ApplicationSpec`, so the OpenAPI
document (and the generated TypeScript client) carry the full spec schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from appspec import ApplicationSpec, SpecSummary, ValidationIssue
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
ChangeSummary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(ApiModel):
    name: Name
    description: Description | None = None


class ProjectOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    current_revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class ProjectPage(ApiModel):
    items: list[ProjectOut]
    next_cursor: str | None = Field(description="Opaque cursor for the next page; null when there are no more.")


class SpecUpdate(ApiModel):
    spec: ApplicationSpec
    change_summary: ChangeSummary | None = None


class SpecRevisionOut(ApiModel):
    project_id: uuid.UUID
    revision: int
    schema_version: str
    content_hash: str
    change_summary: str | None
    created_by: str
    created_at: datetime
    spec: ApplicationSpec
    summary: SpecSummary
    issues: list[ValidationIssue] = Field(description="Non-blocking warnings for the stored revision.")


class SpecRevisionMeta(ApiModel):
    revision: int
    schema_version: str
    content_hash: str
    change_summary: str | None
    created_by: str
    created_at: datetime


class SpecRevisionPage(ApiModel):
    items: list[SpecRevisionMeta]
    next_cursor: str | None


class SpecValidationResult(ApiModel):
    valid: bool
    issues: list[ValidationIssue]
    summary: SpecSummary


class AuditEventOut(ApiModel):
    id: int
    actor: str
    action: str
    occurred_at: datetime
    details: dict[str, Any]


class AuditPage(ApiModel):
    items: list[AuditEventOut]
    next_cursor: str | None


class Health(ApiModel):
    status: str
