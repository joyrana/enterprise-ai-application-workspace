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
from design_system import RenderedScreen, UiDocument, UiIssue
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


class SafetyScanRequest(ApiModel):
    text: Description8k


class SafetySignal(ApiModel):
    kind: str = Field(
        description="instruction_override | role_reassignment | prompt_exfiltration | template_markup | "
        "workflow_tampering | output_directive"
    )
    severity: str = Field(description="high | medium")
    start: int
    end: int
    excerpt: str = Field(description="The sentence containing the signal, truncated.")


class SafetyScan(ApiModel):
    detector: str
    risk: str = Field(description="none | suspicious | high")
    signals: list[SafetySignal]


class FlaggedProposal(ApiModel):
    proposal_id: str
    phrase: str = Field(description="Text from the flagged part of the request that the proposal repeats.")


class RunSafety(SafetyScan):
    flagged_proposals: list[FlaggedProposal] = Field(
        description="Proposals that repeat content from flagged sentences. Review them before accepting."
    )


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
    safety: RunSafety | None = Field(description="Prompt-injection screening of the message; null for older runs.")
    base_revision: int
    summary: str | None
    not_applicable_reason: str | None
    proposals: list[SpecCommand]
    model: RunModelInfo | None
    error: RunError | None
    applied_revision: int | None
    decisions: dict[str, str] | None
    workflow_id: uuid.UUID | None = Field(default=None, description="Set when this run is a workflow step.")
    workflow_step: int | None = Field(default=None, description="Index of the workflow step this run executes.")
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


class WorkflowStepDefinitionOut(ApiModel):
    id: str
    title: str
    skill_id: str


class WorkflowDefinitionOut(ApiModel):
    id: str
    version: str
    name: str
    description: str
    steps: list[WorkflowStepDefinitionOut]
    max_attempts_per_step: int


class WorkflowDefinitionList(ApiModel):
    items: list[WorkflowDefinitionOut]


class WorkflowCreate(ApiModel):
    definition_id: str = Field(max_length=64)
    message: Description8k


class WorkflowStepOut(ApiModel):
    id: str
    title: str
    skill_id: str
    status: str = Field(description="pending | running | awaiting_review | completed | skipped | failed")
    attempts: int
    run_ids: list[uuid.UUID]
    reason: str | None
    applied_revision: int | None


class WorkflowOut(ApiModel):
    id: uuid.UUID
    definition_id: str
    definition_version: str
    name: str
    status: str = Field(description="running | awaiting_review | completed | failed | cancelled")
    current_step: int
    steps: list[WorkflowStepOut]
    message: str
    active_run_id: uuid.UUID | None = Field(description="The step run that is queued or running, if any.")
    can_resume: bool = Field(description="A failed step can be retried, or a stalled step restarted.")
    created_by: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class WorkflowPage(ApiModel):
    items: list[WorkflowOut]


class DesignSystemSummary(ApiModel):
    id: str
    name: str
    version: str
    framework: str
    library_package: str
    library_version: str = Field(description="The library version the contract was checked against.")
    has_adapter: bool


class DesignSystemList(ApiModel):
    items: list[DesignSystemSummary]


class DesignSystemChoice(ApiModel):
    id: str
    version: str
    selected_by: str = Field(description="spec | default")
    note: str | None


class UiPreview(ApiModel):
    spec_revision: int
    design_system: DesignSystemChoice
    document: UiDocument
    issues: list[UiIssue]
    rendered: list[RenderedScreen]
