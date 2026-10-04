from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from appspec import ApplicationSpec, Provenance, Source, load_spec
from model_gateway import Budget, FakeProvider
from skill_sdk import AddItem, AddOpenQuestion, Decision, SkillContext, apply_commands
from workspace_skills import AcceptanceCriteria, ConflictDetection, default_registry
from workspace_skills.discovery.acceptance_criteria import select_targets
from workspace_skills.discovery.conflict_detection import near_duplicates

FINANCE = Path(__file__).resolve().parents[2] / "packages" / "application-spec" / "examples" / "finance-operations.json"
MODEL = Provenance(source=Source.MODEL, skill_id="x", model_id="fake")


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FINANCE.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def finance(raw: dict[str, Any]) -> ApplicationSpec:
    return load_spec(raw)


def ctx(spec: ApplicationSpec, *replies: Any) -> tuple[SkillContext, FakeProvider]:
    provider = FakeProvider(list(replies))
    return SkillContext(spec=spec, provider=provider, budget=Budget()), provider


def test_registry_contains_three_discovery_skills() -> None:
    ids = [m.id for m in default_registry().manifests()]
    assert ids == ["acceptance-criteria", "business-discovery", "requirements-conflict-detection"]


def test_preconditions_gate_skills_on_an_empty_spec(finance: ApplicationSpec) -> None:
    registry = default_registry()
    assert [m.id for m in registry.applicable(ApplicationSpec.empty("x"))] == ["business-discovery"]
    assert len(registry.applicable(finance)) == 3


# --------------------------------------------------------------------------- acceptance criteria


def test_targets_are_requirements_without_criteria(finance: ApplicationSpec) -> None:
    assert [r.id for r in select_targets(finance, "")] == ["validate-source-files", "route-risky-transactions"]


def test_message_narrows_targets(finance: ApplicationSpec) -> None:
    targets = select_targets(finance, "Write acceptance criteria for routing risky transactions for approval")
    assert [r.id for r in targets] == ["route-risky-transactions"]


def test_criteria_only_for_given_requirements_and_capped(finance: ApplicationSpec) -> None:
    answer = {
        "criteria": [
            {"requirement_id": "validate-source-files", "given": "a file", "when": "uploaded", "then": "it is checked"},
            {"requirement_id": "validate-source-files", "given": "a file", "when": "uploaded", "then": "it is checked"},
            {
                "requirement_id": "configure-adjustments",
                "given": "x x",
                "when": "y y",
                "then": "z z",
            },  # already covered
            {"requirement_id": "made-up", "given": "x x", "when": "y y", "then": "z z"},
            *[
                {"requirement_id": "route-risky-transactions", "given": f"case {i}", "when": "sent", "then": "routed"}
                for i in range(5)
            ],
        ]
    }
    context, provider = ctx(finance, answer)
    output = AcceptanceCriteria().run(context, {"message": ""})
    items = [p for p in output.proposals if isinstance(p, AddItem)]
    by_req: dict[str, int] = {}
    for p in items:
        by_req[p.item["requirement_id"]] = by_req.get(p.item["requirement_id"], 0) + 1
    assert by_req == {"validate-source-files": 1, "route-risky-transactions": 3}
    assert all(p.item["id"].startswith("ac-") for p in items)
    prompt = provider.requests[0][1].content
    assert "id: validate-source-files" in prompt
    assert "id: configure-adjustments" not in prompt  # already has criteria


def test_no_model_call_when_everything_is_covered(raw: dict[str, Any]) -> None:
    for i, rid in enumerate(["validate-source-files", "route-risky-transactions"]):
        raw["acceptance_criteria"].append(
            {
                "id": f"ac-extra-{i}",
                "requirement_id": rid,
                "given": "g g",
                "when": "w w",
                "then": "t t",
                "status": "proposed",
                "provenance": {"source": "user"},
            }
        )
    context, provider = ctx(load_spec(raw))
    output = AcceptanceCriteria().run(context, {})
    assert output.proposals == []
    assert output.not_applicable_reason is not None
    assert provider.requests == []


def test_criteria_proposals_apply_cleanly(finance: ApplicationSpec) -> None:
    answer = {"criteria": [{"requirement_id": "validate-source-files", "given": "g g", "when": "w w", "then": "t t"}]}
    context, _ = ctx(finance, answer)
    output = AcceptanceCriteria().run(context, {})
    decisions = {p.proposal_id: Decision.ACCEPT for p in output.proposals}
    updated, results = apply_commands(finance, output.proposals, decisions, provenance=MODEL, actor="u")
    assert [r.outcome.value for r in results] == ["applied"]
    assert len(updated.acceptance_criteria) == 2


# --------------------------------------------------------------------------- conflict detection


def test_near_duplicates_are_found_without_a_model(raw: dict[str, Any]) -> None:
    dup = copy.deepcopy(raw["functional_requirements"][1])
    dup["id"] = "validate-the-source-files"
    dup["title"] = "Validate the uploaded source files"
    raw["functional_requirements"].append(dup)
    assert near_duplicates(load_spec(raw)) == [("validate-source-files", "validate-the-source-files")]


def test_conflicts_must_cite_two_real_elements(finance: ApplicationSpec) -> None:
    answer = {
        "conflicts": [
            {
                "element_ids": ["configure-adjustments", "route-risky-transactions"],
                "explanation": "One applies adjustments immediately, the other requires approval first.",
                "question": "Do adjustments on risky transactions need approval before they apply?",
            },
            {"element_ids": ["configure-adjustments", "ghost"], "explanation": "nope nope", "question": "nope nope?"},
            {
                "element_ids": ["route-risky-transactions", "route-risky-transactions"],
                "explanation": "self x",
                "question": "self?",
            },
        ]
    }
    context, _ = ctx(finance, answer)
    output = ConflictDetection().run(context, {})
    questions = [p for p in output.proposals if isinstance(p, AddOpenQuestion)]
    assert len(questions) == 1
    assert questions[0].blocking is True
    assert questions[0].related_ids == ["configure-adjustments", "route-risky-transactions"]
    assert "Conflict:" in questions[0].question


def test_no_conflicts_is_a_clean_result(finance: ApplicationSpec) -> None:
    context, _ = ctx(finance, {"conflicts": []})
    output = ConflictDetection().run(context, {"message": "check for conflicts"})
    assert output.proposals == []
    assert output.summary == "No conflicts found."
    assert output.not_applicable_reason is None


def test_single_requirement_needs_no_model(raw: dict[str, Any]) -> None:
    raw["functional_requirements"] = raw["functional_requirements"][:1]
    raw["acceptance_criteria"] = []
    raw["screens"][0]["requirement_ids"] = []
    raw["open_questions"] = []
    context, provider = ctx(load_spec(raw))
    output = ConflictDetection().run(context, {})
    assert output.not_applicable_reason is not None
    assert provider.requests == []


def test_conflict_questions_apply_with_related_ids(finance: ApplicationSpec) -> None:
    answer = {
        "conflicts": [
            {
                "element_ids": ["validate-source-files", "route-risky-transactions"],
                "explanation": "Contradiction here.",
                "question": "Which comes first?",
            }
        ]
    }
    context, _ = ctx(finance, answer)
    output = ConflictDetection().run(context, {})
    updated, results = apply_commands(
        finance,
        output.proposals,
        {p.proposal_id: Decision.ACCEPT for p in output.proposals},
        provenance=MODEL,
        actor="u",
    )
    assert results[0].outcome.value == "applied"
    assert updated.open_questions[-1].related_ids == ["route-risky-transactions", "validate-source-files"]
