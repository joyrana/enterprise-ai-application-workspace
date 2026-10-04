from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from appspec import ApplicationSpec, FactStatus, Provenance, Source, load_spec
from skill_sdk import (
    AddItem,
    AddOpenQuestion,
    Category,
    Decision,
    IdAllocator,
    Outcome,
    RegistryError,
    SetFact,
    SkillManifest,
    SkillRegistry,
    apply_commands,
    slugify,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "application-spec" / "examples" / "finance-operations.json"
MODEL = Provenance(source=Source.MODEL, skill_id="business-discovery", skill_version="0.1.0", model_id="fake")


@pytest.fixture
def spec() -> ApplicationSpec:
    return load_spec(json.loads(EXAMPLE.read_text(encoding="utf-8")))


def persona(pid: str = "auditor", name: str = "Auditor") -> AddItem:
    return AddItem(proposal_id=f"p-{pid}", collection="personas", item={"id": pid, "name": name})


# --------------------------------------------------------------------------- apply_commands


def test_accept_adds_proposed_item_with_model_provenance(spec: ApplicationSpec) -> None:
    updated, results = apply_commands(spec, [persona()], {"p-auditor": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    added = next(p for p in updated.personas if p.id == "auditor")
    assert added.status == "proposed"
    assert added.confirmed_by is None
    assert added.provenance == MODEL
    assert results[0].outcome is Outcome.APPLIED


def test_confirm_records_the_deciding_user(spec: ApplicationSpec) -> None:
    updated, _ = apply_commands(spec, [persona()], {"p-auditor": Decision.CONFIRM}, provenance=MODEL, actor="alice")
    added = next(p for p in updated.personas if p.id == "auditor")
    assert (added.status, added.confirmed_by) == ("confirmed", "alice")


def test_skill_cannot_smuggle_status_or_provenance(spec: ApplicationSpec) -> None:
    sneaky = AddItem(
        proposal_id="p-x",
        collection="personas",
        item={"id": "x", "name": "X", "status": "confirmed", "confirmed_by": "ceo", "provenance": {"source": "user"}},
    )
    updated, _ = apply_commands(spec, [sneaky], {"p-x": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    added = next(p for p in updated.personas if p.id == "x")
    assert added.status == "proposed"
    assert added.confirmed_by is None
    assert added.provenance.source is Source.MODEL


def test_confirmed_fact_is_never_overwritten(spec: ApplicationSpec) -> None:
    assert spec.objective.status is FactStatus.CONFIRMED
    command = SetFact(proposal_id="p-objective", path="/objective", value="Something else entirely")
    updated, results = apply_commands(spec, [command], {"p-objective": Decision.CONFIRM}, provenance=MODEL, actor="u1")
    assert updated.objective == spec.objective
    assert results[0].outcome is Outcome.SKIPPED_CONFIRMED_FACT


def test_proposed_fact_can_be_replaced_and_confirmed(spec: ApplicationSpec) -> None:
    assert spec.domain.status is FactStatus.PROPOSED
    command = SetFact(proposal_id="p-domain", path="/domain", value="Corporate finance")
    updated, _ = apply_commands(spec, [command], {"p-domain": Decision.CONFIRM}, provenance=MODEL, actor="bob")
    assert updated.domain.value == "Corporate finance"
    assert updated.domain.status is FactStatus.CONFIRMED
    assert updated.domain.confirmed_by == "bob"


def test_invalid_enum_fact_is_rejected(spec: ApplicationSpec) -> None:
    command = SetFact(proposal_id="p-c", path="/security/classification", value="top-secret")
    updated, results = apply_commands(spec, [command], {"p-c": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    assert results[0].outcome is Outcome.INVALID
    assert updated == spec


def test_existing_id_is_never_replaced(spec: ApplicationSpec) -> None:
    clash = persona("ops-analyst", "Impostor")
    updated, results = apply_commands(spec, [clash], {"p-ops-analyst": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    assert results[0].outcome is Outcome.SKIPPED_ID_CONFLICT
    assert next(p for p in updated.personas if p.id == "ops-analyst").name == "Operations analyst"


def test_rejected_and_undecided_commands_change_nothing(spec: ApplicationSpec) -> None:
    updated, results = apply_commands(
        spec, [persona("a", "A"), persona("b", "B")], {"p-a": Decision.REJECT}, provenance=MODEL, actor="u1"
    )
    assert updated == spec
    assert [r.outcome for r in results] == [Outcome.REJECTED_BY_USER, Outcome.REJECTED_BY_USER]


def test_requirement_referencing_rejected_persona_is_not_applied(spec: ApplicationSpec) -> None:
    requirement = AddItem(
        proposal_id="p-req",
        collection="functional_requirements",
        item={"id": "audit-trail", "title": "Review audit trail", "persona_ids": ["auditor"]},
    )
    updated, results = apply_commands(
        spec,
        [persona(), requirement],
        {"p-auditor": Decision.REJECT, "p-req": Decision.ACCEPT},
        provenance=MODEL,
        actor="u1",
    )
    assert results[1].outcome is Outcome.WOULD_BREAK_REFERENCES
    assert all(r.id != "audit-trail" for r in updated.functional_requirements)


def test_requirement_referencing_accepted_persona_is_applied(spec: ApplicationSpec) -> None:
    requirement = AddItem(
        proposal_id="p-req",
        collection="functional_requirements",
        item={"id": "audit-trail", "title": "Review audit trail", "persona_ids": ["auditor"]},
    )
    _, results = apply_commands(
        spec,
        [persona(), requirement],
        {"p-auditor": Decision.ACCEPT, "p-req": Decision.ACCEPT},
        provenance=MODEL,
        actor="u",
    )
    assert [r.outcome for r in results] == [Outcome.APPLIED, Outcome.APPLIED]


def test_invalid_item_is_reported(spec: ApplicationSpec) -> None:
    bad = AddItem(proposal_id="p-bad", collection="personas", item={"id": "Bad Id", "name": "x"})
    _, results = apply_commands(spec, [bad], {"p-bad": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    assert results[0].outcome is Outcome.INVALID


def test_duplicate_open_question_is_skipped(spec: ApplicationSpec) -> None:
    existing = spec.open_questions[0].question
    command = AddOpenQuestion(proposal_id="p-q", question_id="q-new", question=f"  {existing.upper()} ")
    _, results = apply_commands(spec, [command], {"p-q": Decision.ACCEPT}, provenance=MODEL, actor="u1")
    assert results[0].outcome is Outcome.SKIPPED_DUPLICATE


def test_apply_does_not_mutate_input(spec: ApplicationSpec) -> None:
    before = spec.model_dump()
    apply_commands(spec, [persona()], {"p-auditor": Decision.CONFIRM}, provenance=MODEL, actor="u1")
    assert spec.model_dump() == before


# --------------------------------------------------------------------------- ids


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Finance Approver", "finance-approver"),
        ("  Café Ops & Review!! ", "cafe-ops-review"),
        ("123 numbers first", "item-123-numbers-first"),
        ("!!!", "item"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_id_allocator_avoids_taken_and_batch_collisions() -> None:
    ids = IdAllocator(["approver"])
    assert ids.allocate("Approver") == "approver-2"
    assert ids.allocate("approver") == "approver-3"
    assert ids.allocate("What is the threshold?", prefix="q") == "q-what-is-the-threshold"


def test_long_ids_stay_within_limit() -> None:
    ids = IdAllocator([])
    first = ids.allocate("x" * 200)
    second = ids.allocate("x" * 200)
    assert len(first) <= 64
    assert len(second) <= 64
    assert first != second


# --------------------------------------------------------------------------- registry


def manifest(skill_id: str, version: str = "1.0.0", **kwargs: Any) -> SkillManifest:
    return SkillManifest(
        id=skill_id,
        name=skill_id,
        description="d",
        version=version,
        category=Category.DISCOVERY,
        completion_criteria="c",
        failure_behavior="f",
        **kwargs,
    )


class _Skill:
    def __init__(self, m: SkillManifest) -> None:
        self.manifest = m

    def run(self, context: Any, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError


def test_registry_versions_and_latest() -> None:
    registry = SkillRegistry()
    registry.register(_Skill(manifest("a", "1.2.0")))  # type: ignore[arg-type]
    registry.register(_Skill(manifest("a", "1.10.0")))  # type: ignore[arg-type]
    assert registry.get("a").manifest.version == "1.10.0"
    assert registry.get("a", "1.2.0").manifest.version == "1.2.0"
    with pytest.raises(RegistryError):
        registry.register(_Skill(manifest("a", "1.2.0")))  # type: ignore[arg-type]
    with pytest.raises(RegistryError):
        registry.get("missing")


def test_registry_rejects_unknown_dependencies() -> None:
    with pytest.raises(RegistryError, match="depends on"):
        SkillRegistry().register(_Skill(manifest("b", depends_on=("a",))))  # type: ignore[arg-type]


def test_applicability_uses_preconditions_without_a_model(spec: ApplicationSpec) -> None:
    registry = SkillRegistry()
    registry.register(_Skill(manifest("needs-objective", preconditions=("/objective",))))  # type: ignore[arg-type]
    registry.register(_Skill(manifest("needs-design-system", preconditions=("/design_system/id",))))  # type: ignore[arg-type]
    registry.register(_Skill(manifest("needs-personas", preconditions=("/personas",))))  # type: ignore[arg-type]
    assert [m.id for m in registry.applicable(spec)] == ["needs-objective", "needs-personas"]
    assert registry.applicable(ApplicationSpec.empty("x")) == []
