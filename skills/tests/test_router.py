from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from appspec import ApplicationSpec, load_spec
from model_gateway import Budget, ErrorKind, FakeProvider, ModelError
from skill_sdk import RoutingError, SkillRouter, lexical_choice
from workspace_skills import default_registry

FINANCE = Path(__file__).resolve().parents[2] / "packages" / "application-spec" / "examples" / "finance-operations.json"


@pytest.fixture
def finance() -> ApplicationSpec:
    return load_spec(json.loads(FINANCE.read_text(encoding="utf-8")))


@pytest.fixture
def router() -> SkillRouter:
    return SkillRouter(default_registry())


def test_single_candidate_needs_no_model(router: SkillRouter) -> None:
    provider = FakeProvider([])
    decision = router.route("anything", ApplicationSpec.empty("x"), provider=provider, budget=Budget())
    assert decision.skill_id == "business-discovery"
    assert decision.method == "single-candidate"
    assert provider.requests == []


def test_model_chooses_among_candidates(router: SkillRouter, finance: ApplicationSpec) -> None:
    provider = FakeProvider([{"skill_id": "acceptance-criteria", "confidence": 0.9, "rationale": "asks for tests"}])
    decision = router.route("How will we test approvals?", finance, provider=provider, budget=Budget())
    assert decision.skill_id == "acceptance-criteria"
    assert decision.method == "model"
    assert decision.confidence == 0.9
    assert decision.candidates == ["acceptance-criteria", "business-discovery", "requirements-conflict-detection"]
    assert decision.model is not None
    assert decision.model["prompt_version"] == "router@1"
    prompt = provider.requests[0][1].content
    assert "<user_message>" in prompt
    assert "id: requirements-conflict-detection" in prompt


def test_model_may_choose_none(router: SkillRouter, finance: ApplicationSpec) -> None:
    provider = FakeProvider([{"skill_id": "none", "confidence": 0.8, "rationale": "weather question"}])
    decision = router.route("Will it rain?", finance, provider=provider, budget=Budget())
    assert decision.skill_id is None


def test_invented_skill_ids_are_repaired_then_rejected(router: SkillRouter, finance: ApplicationSpec) -> None:
    provider = FakeProvider(
        [
            {"skill_id": "deploy-to-prod", "confidence": 1, "rationale": "x"},
            {"skill_id": "requirements-conflict-detection", "confidence": 0.7, "rationale": "fixed"},
        ]
    )
    decision = router.route("Any contradictions?", finance, provider=provider, budget=Budget())
    assert decision.skill_id == "requirements-conflict-detection"
    assert decision.model is not None
    assert decision.model["repaired"] is True


def test_routing_failure_is_not_silently_replaced(router: SkillRouter, finance: ApplicationSpec) -> None:
    provider = FakeProvider([ModelError(ErrorKind.TIMEOUT)])
    with pytest.raises(ModelError):
        router.route("Write acceptance criteria", finance, provider=provider, budget=Budget())


def test_no_model_with_several_candidates_is_reported(router: SkillRouter, finance: ApplicationSpec) -> None:
    with pytest.raises(ModelError) as info:
        router.route("x", finance, provider=None, budget=Budget())
    assert info.value.kind is ErrorKind.NOT_CONFIGURED


def test_explicit_choice_is_validated(router: SkillRouter, finance: ApplicationSpec) -> None:
    decision = router.route("x", finance, provider=None, budget=Budget(), explicit="acceptance-criteria")
    assert (decision.skill_id, decision.method) == ("acceptance-criteria", "explicit")
    with pytest.raises(RoutingError, match="needs /functional_requirements"):
        router.route("x", ApplicationSpec.empty("e"), provider=None, budget=Budget(), explicit="acceptance-criteria")
    with pytest.raises(RoutingError, match="unknown skill"):
        router.route("x", finance, provider=None, budget=Budget(), explicit="nope")


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Write acceptance criteria for the approval requirement", "acceptance-criteria"),
        ("Are any requirements contradictory or duplicated?", "requirements-conflict-detection"),
        ("Hello there", None),
    ],
)
def test_lexical_baseline(message: str, expected: str | None, finance: ApplicationSpec) -> None:
    choice, scores = lexical_choice(message, default_registry().applicable(finance))
    assert choice == expected
    assert set(scores) == {"acceptance-criteria", "business-discovery", "requirements-conflict-detection"}


def test_lexical_ties_choose_nothing() -> None:
    assert lexical_choice("x", [])[0] is None


def test_decision_serializes(router: SkillRouter) -> None:
    decision = router.route("x", ApplicationSpec.empty("e"), provider=None, budget=Budget())
    data: dict[str, Any] = decision.model_dump()
    assert data["method"] == "single-candidate"


def test_over_long_rationale_is_truncated_not_failed(finance: ApplicationSpec) -> None:
    long = "Because " + "the request clearly asks for discovery work " * 20
    provider = FakeProvider([{"skill_id": "business-discovery", "confidence": 0.7, "rationale": long}])
    decision = SkillRouter(default_registry()).route(
        "Add a new module for vendor onboarding", finance, provider=provider, budget=Budget(max_calls=2)
    )
    assert decision.skill_id == "business-discovery"
    assert len(decision.rationale) <= 400
    assert decision.rationale.endswith("…")
    assert len(provider.requests) == 1  # no repair call spent on it
