"""Checkpointed multi-step workflows: definitions and pure state transitions (ADR-0012).

A workflow is an ordered list of steps. Each step runs one skill as an ordinary
AI run; a step with proposals waits for a person to apply (or reject) them, and
the next step starts from the revision that produced. Control flow is decided
here, deterministically — never by a model.

This module has no I/O. The API persists :class:`WorkflowState` as a checkpoint
in the same transaction as the event that changed it, so progress survives
crashes and restarts.

Step lifecycle::

    pending ──start──▶ running ──proposals──▶ awaiting_review ──applied──▶ completed
       │                  ├──no proposals──────────────────────────────▶ completed
       │                  └──failed──▶ failed ──resume (bounded)──▶ pending
       └──preconditions unmet──▶ skipped
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED})


class WorkflowError(Exception):
    """A transition that is not allowed in the current state."""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StepDefinition(_Frozen):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    title: str
    skill_id: str
    #: Request text for this step; ``None`` means the text the person started the workflow with.
    message: str | None = None


class WorkflowDefinition(_Frozen):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}$")
    version: str
    name: str
    description: str
    steps: tuple[StepDefinition, ...] = Field(min_length=1, max_length=10)
    max_attempts_per_step: int = Field(default=2, ge=1, le=5)


class StepState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    run_ids: list[str] = Field(default_factory=list)
    reason: str | None = None
    applied_revision: int | None = None


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: WorkflowStatus = WorkflowStatus.RUNNING
    current: int = 0
    steps: list[StepState]

    @property
    def step(self) -> StepState | None:
        return self.steps[self.current] if self.current < len(self.steps) else None


RunOutcome = Literal["proposals", "empty", "failed"]


@dataclass(frozen=True)
class StartStep:
    index: int
    skill_id: str
    message: str


@dataclass(frozen=True)
class Wait:
    """Nothing to do until a run finishes or a person acts."""


@dataclass(frozen=True)
class Finished:
    pass


Action = StartStep | Wait | Finished


def start(definition: WorkflowDefinition) -> WorkflowState:
    return WorkflowState(steps=[StepState(step_id=s.id) for s in definition.steps])


def _copy(state: WorkflowState) -> WorkflowState:
    return state.model_copy(deep=True)


def advance(
    definition: WorkflowDefinition,
    state: WorkflowState,
    message: str,
    unmet: Callable[[str], list[str]],
) -> tuple[WorkflowState, Action]:
    """Move past completed and skippable steps; say what to start next.

    ``unmet(skill_id)`` returns the skill's unmet preconditions against the
    *current* specification, so a step whose inputs the person rejected is
    skipped with a reason instead of failing.
    """
    state = _copy(state)
    if state.status in TERMINAL or state.status is WorkflowStatus.FAILED:
        return state, Wait()
    while state.current < len(state.steps):
        step = state.steps[state.current]
        if step.status in (StepStatus.COMPLETED, StepStatus.SKIPPED):
            state.current += 1
            continue
        if step.status is StepStatus.RUNNING:
            state.status = WorkflowStatus.RUNNING
            return state, Wait()
        if step.status is StepStatus.AWAITING_REVIEW:
            state.status = WorkflowStatus.AWAITING_REVIEW
            return state, Wait()
        if step.status is StepStatus.FAILED:
            state.status = WorkflowStatus.FAILED
            return state, Wait()
        definition_step = definition.steps[state.current]
        missing = unmet(definition_step.skill_id)
        if missing:
            step.status = StepStatus.SKIPPED
            step.reason = "Needs " + ", ".join(missing) + " in the specification."
            state.current += 1
            continue
        state.status = WorkflowStatus.RUNNING
        return state, StartStep(
            index=state.current,
            skill_id=definition_step.skill_id,
            message=definition_step.message or message,
        )
    state.status = WorkflowStatus.COMPLETED
    return state, Finished()


def step_started(definition: WorkflowDefinition, state: WorkflowState, index: int, run_id: str) -> WorkflowState:
    state = _copy(state)
    step = _expect(state, index, StepStatus.PENDING)
    if step.attempts >= definition.max_attempts_per_step:
        raise WorkflowError(f"Step '{step.step_id}' already used {step.attempts} attempt(s).")
    step.attempts += 1
    step.run_ids.append(run_id)
    step.status = StepStatus.RUNNING
    step.reason = None
    state.status = WorkflowStatus.RUNNING
    return state


def run_finished(state: WorkflowState, run_id: str, outcome: RunOutcome, reason: str | None = None) -> WorkflowState:
    """Record the end of a step's run. Runs that are not the step's latest are ignored."""
    state = _copy(state)
    index = _index_of_latest(state, run_id)
    if index is None or state.status is WorkflowStatus.CANCELLED:
        return state
    step = state.steps[index]
    if step.status is not StepStatus.RUNNING:
        return state  # already recorded (idempotent)
    if outcome == "proposals":
        step.status = StepStatus.AWAITING_REVIEW
        state.status = WorkflowStatus.AWAITING_REVIEW
    elif outcome == "empty":
        step.status = StepStatus.COMPLETED
        step.reason = reason
    else:
        step.status = StepStatus.FAILED
        step.reason = reason
        state.status = WorkflowStatus.FAILED
    return state


def run_applied(state: WorkflowState, run_id: str, revision: int | None) -> WorkflowState:
    """The person decided on the step's proposals (``revision`` is None if they rejected all)."""
    state = _copy(state)
    index = _index_of_latest(state, run_id)
    if index is None or state.status is WorkflowStatus.CANCELLED:
        return state
    step = state.steps[index]
    if step.status is not StepStatus.AWAITING_REVIEW:
        return state
    step.status = StepStatus.COMPLETED
    step.applied_revision = revision
    step.reason = None if revision is not None else "All proposals were rejected."
    state.status = WorkflowStatus.RUNNING
    return state


def resume(definition: WorkflowDefinition, state: WorkflowState) -> WorkflowState:
    """Retry a failed step (bounded). Raises :class:`WorkflowError` when not resumable."""
    state = _copy(state)
    if state.status in TERMINAL:
        raise WorkflowError(f"The workflow is {state.status.value}.")
    step = state.step
    if step is None:
        raise WorkflowError("The workflow has no remaining steps.")
    if step.status is StepStatus.FAILED:
        if step.attempts >= definition.max_attempts_per_step:
            raise WorkflowError(
                f"Step '{step.step_id}' failed {step.attempts} time(s), the maximum. Start a new workflow."
            )
        step.status = StepStatus.PENDING
        state.status = WorkflowStatus.RUNNING
        return state
    if step.status is StepStatus.PENDING:
        return state  # stalled before its run was created; advancing will start it
    raise WorkflowError(f"Step '{step.step_id}' is {step.status.value}; nothing to resume.")


def cancel(state: WorkflowState) -> WorkflowState:
    state = _copy(state)
    if state.status in TERMINAL:
        raise WorkflowError(f"The workflow is already {state.status.value}.")
    state.status = WorkflowStatus.CANCELLED
    return state


def _expect(state: WorkflowState, index: int, status: StepStatus) -> StepState:
    if index != state.current or index >= len(state.steps):
        raise WorkflowError(f"Step {index} is not the current step.")
    step = state.steps[index]
    if step.status is not status:
        raise WorkflowError(f"Step '{step.step_id}' is {step.status.value}, expected {status.value}.")
    return step


def _index_of_latest(state: WorkflowState, run_id: str) -> int | None:
    for i, step in enumerate(state.steps):
        if step.run_ids and step.run_ids[-1] == run_id:
            return i
    return None


#: Built-in workflows. Versioned: a change to steps means a new version.
REQUIREMENTS_PIPELINE = WorkflowDefinition(
    id="requirements-pipeline",
    version="1",
    name="Requirements pipeline",
    description=(
        "Discovery, then acceptance criteria for the requirements you accepted, then a conflict check. "
        "Pauses for your review after each step that proposes changes."
    ),
    steps=(
        StepDefinition(id="discover", title="Discover requirements", skill_id="business-discovery"),
        StepDefinition(
            id="criteria",
            title="Write acceptance criteria",
            skill_id="acceptance-criteria",
            message="Write acceptance criteria for the requirements.",
        ),
        StepDefinition(
            id="conflicts",
            title="Check for conflicts",
            skill_id="requirements-conflict-detection",
            message="Check the requirements for conflicts and duplicates.",
        ),
    ),
)

BUILT_IN_WORKFLOWS: dict[str, WorkflowDefinition] = {REQUIREMENTS_PIPELINE.id: REQUIREMENTS_PIPELINE}
