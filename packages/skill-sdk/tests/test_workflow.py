from __future__ import annotations

from collections.abc import Callable

import pytest

from skill_sdk.workflow import (
    REQUIREMENTS_PIPELINE,
    Action,
    Finished,
    StartStep,
    StepStatus,
    Wait,
    WorkflowError,
    WorkflowState,
    WorkflowStatus,
    advance,
    cancel,
    resume,
    run_applied,
    run_finished,
    start,
    step_started,
)

D = REQUIREMENTS_PIPELINE


def nothing_missing(skill_id: str) -> list[str]:
    return []


def go(state: WorkflowState, unmet: Callable[[str], list[str]] = nothing_missing) -> tuple[WorkflowState, Action]:
    return advance(D, state, "Finance ops app", unmet)


def started(state: WorkflowState, run_id: str) -> WorkflowState:
    state, action = go(state)
    assert isinstance(action, StartStep)
    return step_started(D, state, action.index, run_id)


def test_happy_path_pauses_for_review_after_each_step_with_proposals() -> None:
    state, action = go(start(D))
    assert action == StartStep(index=0, skill_id="business-discovery", message="Finance ops app")
    state = step_started(D, state, 0, "r1")
    assert state.steps[0].status is StepStatus.RUNNING
    assert state.steps[0].attempts == 1

    state = run_finished(state, "r1", "proposals")
    assert state.status is WorkflowStatus.AWAITING_REVIEW
    assert isinstance(go(state)[1], Wait)  # nothing starts before the person decides

    state = run_applied(state, "r1", revision=2)
    assert state.steps[0].status is StepStatus.COMPLETED
    assert state.steps[0].applied_revision == 2
    state, action = go(state)
    assert action == StartStep(index=1, skill_id="acceptance-criteria", message=D.steps[1].message or "")

    state = step_started(D, state, 1, "r2")
    state = run_finished(state, "r2", "proposals")
    state = run_applied(state, "r2", revision=3)
    state = step_started(D, *_start_args(state, 2, "r3"))
    state = run_finished(state, "r3", "empty", "No conflicts found.")
    state, action = go(state)
    assert isinstance(action, Finished)
    assert state.status is WorkflowStatus.COMPLETED
    assert [s.status for s in state.steps] == [StepStatus.COMPLETED] * 3
    assert state.steps[2].reason == "No conflicts found."


def _start_args(state: WorkflowState, index: int, run_id: str) -> tuple[WorkflowState, int, str]:
    state, action = go(state)
    assert isinstance(action, StartStep)
    assert action.index == index
    return state, index, run_id


def test_rejecting_everything_completes_the_step_and_skips_steps_without_inputs() -> None:
    state = started(start(D), "r1")
    state = run_finished(state, "r1", "proposals")
    state = run_applied(state, "r1", revision=None)
    assert state.steps[0].reason == "All proposals were rejected."

    def unmet(skill_id: str) -> list[str]:
        return ["/functional_requirements"]

    state, action = go(state, unmet)
    assert isinstance(action, Finished)
    assert [s.status for s in state.steps[1:]] == [StepStatus.SKIPPED, StepStatus.SKIPPED]
    assert state.steps[1].reason == "Needs /functional_requirements in the specification."


def test_failure_is_resumable_a_bounded_number_of_times() -> None:
    state = started(start(D), "r1")
    state = run_finished(state, "r1", "failed", "interrupted")
    assert state.status is WorkflowStatus.FAILED
    assert isinstance(go(state)[1], Wait)  # a failed workflow never advances by itself

    state = resume(D, state)
    state = started(state, "r2")
    assert state.steps[0].attempts == 2
    assert state.steps[0].run_ids == ["r1", "r2"]
    state = run_finished(state, "r2", "failed", "timeout")
    with pytest.raises(WorkflowError, match="maximum"):
        resume(D, state)


def test_events_for_superseded_runs_and_repeats_are_ignored() -> None:
    state = started(start(D), "r1")
    state = run_finished(state, "r1", "failed")
    state = started(resume(D, state), "r2")
    assert run_finished(state, "r1", "proposals") == state  # r1 is not the latest run
    once = run_finished(state, "r2", "proposals")
    assert run_finished(once, "r2", "failed") == once  # already recorded
    assert run_applied(state, "r2", 2) == state  # cannot apply before it awaits review


def test_resume_restarts_a_stalled_step_and_refuses_otherwise() -> None:
    state, _ = go(start(D))  # step 0 pending, no run created (e.g. crash before insert)
    assert resume(D, state).steps[0].status is StepStatus.PENDING
    running = started(start(D), "r1")
    with pytest.raises(WorkflowError, match="nothing to resume"):
        resume(D, running)


def test_cancel_is_final_and_ignores_late_events() -> None:
    state = cancel(started(start(D), "r1"))
    assert state.status is WorkflowStatus.CANCELLED
    assert run_finished(state, "r1", "proposals").status is WorkflowStatus.CANCELLED
    assert isinstance(go(state)[1], Wait)
    with pytest.raises(WorkflowError):
        cancel(state)
    with pytest.raises(WorkflowError):
        resume(D, state)


def test_step_can_only_start_when_current_and_pending() -> None:
    state, _ = go(start(D))
    with pytest.raises(WorkflowError, match="not the current step"):
        step_started(D, state, 1, "r1")
    state = step_started(D, state, 0, "r1")
    with pytest.raises(WorkflowError, match="expected pending"):
        step_started(D, state, 0, "r2")


def test_state_round_trips_as_json_checkpoint() -> None:
    state = started(start(D), "r1")
    assert WorkflowState.model_validate(state.model_dump(mode="json")) == state
