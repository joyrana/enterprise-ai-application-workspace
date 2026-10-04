"""Tests of the evaluation harness itself, using a fake provider. These say nothing about model quality."""

from __future__ import annotations

from typing import Any

from model_gateway import ErrorKind, FakeProvider, ModelError
from workspace_evals.discovery import (
    DEFAULT_DATASET,
    Checks,
    Scenario,
    load_scenarios,
    markdown,
    run_suite,
)

GOOD: dict[str, Any] = {
    "is_application_request": True,
    "objective": "Speed up onboarding",
    "personas": [{"name": "HR coordinator"}, {"name": "Manager"}],
    "requirements": [
        {"title": "Collect new-hire documents"},
        {"title": "Assign equipment"},
        {"title": "Schedule orientation"},
        {"title": "Track onboarding progress"},
    ],
    "open_questions": [{"question": "Which HR system holds employee records?"}],
}


def scenario(**checks: Any) -> Scenario:
    return Scenario(
        id="s", starting_spec="empty", description="HR onboarding", checks=Checks(expect_application=True, **checks)
    )


def test_dataset_loads_and_ids_are_unique() -> None:
    scenarios = load_scenarios(DEFAULT_DATASET)
    assert len(scenarios) >= 8
    assert len({s.id for s in scenarios}) == len(scenarios)
    assert any(not s.checks.expect_application for s in scenarios)
    assert any(s.starting_spec == "finance-example" for s in scenarios)


def test_passing_trial() -> None:
    s = scenario(min_personas=2, min_requirements=3, requirements_mention_any=[["document"], ["equipment"]])
    trials, summary = run_suite([s], lambda: FakeProvider([GOOD]))
    assert trials[0].passed
    assert summary["pass_rate"] == 1.0
    assert summary["completion_rate"] == 1.0


def test_failed_checks_are_named() -> None:
    s = scenario(min_open_questions=3, requirements_mention_any=[["payroll"]], forbidden_substrings=["onboarding"])
    trials, summary = run_suite([s], lambda: FakeProvider([GOOD]))
    assert not trials[0].passed
    assert summary["scenarios"]["s"]["failed_checks"] == [
        "forbidden:onboarding",
        "mentions:payroll",
        "open_questions_count",
    ]


def test_model_errors_count_as_incomplete_not_crashes() -> None:
    trials, summary = run_suite([scenario()], lambda: FakeProvider([ModelError(ErrorKind.TIMEOUT)]), repeats=2)
    assert summary["completion_rate"] == 0.0
    assert summary["errors"] == {"timeout": 2}
    assert all(not t.passed for t in trials)


def test_non_application_scenario() -> None:
    s = Scenario(id="w", starting_spec="empty", description="weather?", checks=Checks(expect_application=False))
    reply = {"is_application_request": False, "not_applicable_reason": "weather"}
    trials, _ = run_suite([s], lambda: FakeProvider([reply]))
    assert trials[0].passed


def test_repeats_and_pass_fraction() -> None:
    replies = [GOOD, {"is_application_request": False}]
    provider_iter = iter([FakeProvider([r]) for r in replies])
    _, summary = run_suite([scenario()], lambda: next(provider_iter), repeats=2)
    assert summary["scenarios"]["s"]["pass_fraction"] == 0.5


def test_markdown_report_renders() -> None:
    _, summary = run_suite([scenario()], lambda: FakeProvider([GOOD]))
    text = markdown(
        {
            "model": "fake:fake-model",
            "dataset": "evals/datasets/discovery/v1.jsonl",
            "scenarios": 1,
            "repeats": 1,
            "prompt_version": "business-discovery@1",
            "skill": "business-discovery@0.1.0",
            "run_at": "2026-10-04T00:00:00+00:00",
            "summary": summary,
        }
    )
    assert "| s | 100% | — |" in text
