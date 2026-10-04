"""Request and response contracts for API v1.

The spec itself is typed as :class:`appspec.ApplicationSpec`, so the OpenAPI
document (and the generated TypeScript client) carry the full spec schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from appspec import ApplicationSpec, SpecSummary, ValidationIssue
from skill_sdk import CommandResult, Decision, SpecCommand

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


# --------------------------------------------------------------------------- AI runs

Description8k = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]


class AiStatus(ApiModel):
    configured: bool
    model: str | None = Field(description="profile:model identifier, e.g. 'ollama:gpt-oss:20b'.")
    profile: str | None
    remote: bool | None = Field(description="Whether prompts leave the organization's network.")
    structured_mode: str | None


class RunCreate(ApiModel):
    message: Description8k
    skill_id: str | None = Field(
        default=None,
        max_length=64,
        description="Run this skill. Omit to let the workspace route the request to the best applicable skill.",
    )


class SkillInfo(ApiModel):
    id: str
    name: str
    description: str
    category: str
    version: str
    applicable: bool
    unmet_preconditions: list[str]
    message_required: bool


class SkillList(ApiModel):
    items: list[SkillInfo]


class RunRouting(ApiModel):
    method: str = Field(description="explicit | single-candidate | model | no-candidates")
    candidates: list[str]
    chosen: str | None
    confidence: float | None
    rationale: str
    model_id: str | None
    total_tokens: int


class RunError(ApiModel):
    kind: str
    message: str


class ModelUsage(ApiModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class RunModelInfo(ApiModel):
    model_id: str
    profile: str
    prompt_version: str | None
    usage: ModelUsage
    repaired: bool
    calls: int
    latency_ms: float
    estimated_cost_usd: float | None


class RunOut(ApiModel):
    id: uuid.UUID
    skill_id: str | None = Field(description="Null until routing chooses a skill, or when no skill fits.")
    skill_version: str | None
    status: str = Field(description="queued | running | succeeded | failed")
    message: str
    routing: RunRouting | None
    base_revision: int
    summary: str | None
    not_applicable_reason: str | None
    proposals: list[SpecCommand]
    model: RunModelInfo | None
    error: RunError | None
    applied_revision: int | None
    decisions: dict[str, str] | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunPage(ApiModel):
    items: list[RunOut]


class ProposalDecision(ApiModel):
    proposal_id: str = Field(min_length=1, max_length=64)
    decision: Decision


class ApplyRunRequest(ApiModel):
    decisions: list[ProposalDecision] = Field(min_length=1, max_length=200)
    change_summary: ChangeSummary | None = None


class ApplyRunResult(ApiModel):
    run: RunOut
    results: list[CommandResult]
    revision: SpecRevisionOut
    revision_created: bool
