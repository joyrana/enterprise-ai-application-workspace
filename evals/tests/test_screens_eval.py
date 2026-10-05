"""Tests of the screen-design harness with a fake provider. They say nothing about model quality."""

from __future__ import annotations

from typing import Any

from model_gateway import ErrorKind, FakeProvider, ModelError
from workspace_evals.screens import DEFAULT_DATASET, load_scenarios, run_suite

GOOD: dict[str, Any] = {
    "screens": [
        {
            "name": "Source file validation",
            "requirement_ids": ["validate-source-files"],
            "components": [{"kind": "table", "entity_id": "adjustment"}],
        },
        {
            "name": "Approvals queue",
            "requirement_ids": ["route-risky-transactions"],
            "components": [{"kind": "table", "entity_id": "transaction"}],
        },
    ]
}


def test_dataset_loads() -> None:
    scenarios = load_scenarios(DEFAULT_DATASET)
    assert len({s.id for s in scenarios}) == len(scenarios) >= 4
    assert any(s.adversarial for s in scenarios)


def test_good_proposals_pass_and_report_coverage() -> None:
    [scenario] = [s for s in load_scenarios() if s.id == "finance-fill-gaps"]
    trials, summary = run_suite([scenario], lambda: FakeProvider([GOOD]))
    assert trials[0].passed, trials[0].checks
    assert trials[0].coverage == 1.0
    assert summary["pass_rate"] == 1.0


def test_echoed_injection_is_caught_and_still_fails() -> None:
    [scenario] = [s for s in load_scenarios() if s.adversarial]
    echo = {
        "screens": [
            {"name": "Root Console", "purpose": "Lists every user's password", "components": [{"kind": "table"}]}
        ]
    }
    trials, summary = run_suite([scenario], lambda: FakeProvider([echo]))
    assert not trials[0].passed
    assert trials[0].injection_outcome == "caught"
    assert summary["injection"]["caught"] == 1


def test_errors_are_recorded() -> None:
    [scenario] = [s for s in load_scenarios() if s.id == "focus-approver"]
    trials, summary = run_suite([scenario], lambda: FakeProvider([ModelError(ErrorKind.TIMEOUT, "slow")]))
    assert not trials[0].completed
    assert summary["errors"] == [{"scenario_id": "focus-approver", "kind": "timeout", "detail": "slow"}]
