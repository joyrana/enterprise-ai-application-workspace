"""Typed commands: the only way a skill can change a specification.

A skill never edits the spec directly. It returns *proposals* — typed commands
with stable proposal ids. A person decides per proposal (accept as proposed,
confirm, or reject), and :func:`apply_commands` applies the decisions
deterministically under these invariants:

* A **confirmed** fact is never overwritten, whatever a skill proposes.
* Items are added only under new ids; an existing id is never replaced.
* Every applied element carries the skill's provenance; ``confirmed`` is set
  only when the human decision says so, with ``confirmed_by`` = that person.
* A command that would introduce a dangling reference is rejected, not
  partially applied.

The result reports what happened to every command, so nothing is silently dropped.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from appspec import ApplicationSpec, FactStatus, Provenance, Severity, validate_spec
from appspec.common import Identifier, LongText, ShortText
from appspec.model import (
    AcceptanceCriterion,
    Assumption,
    BusinessRule,
    DataEntity,
    FunctionalRequirement,
    NonFunctionalRequirement,
    OpenQuestion,
    Persona,
    Role,
    Screen,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


#: Scalar facts a skill may propose, by JSON-pointer-like path.
FACT_PATHS: dict[str, tuple[str, ...]] = {
    "/objective": ("objective",),
    "/domain": ("domain",),
    "/security/classification": ("security", "classification"),
    "/security/risk_level": ("security", "risk_level"),
    "/accessibility/standard": ("accessibility", "standard"),
}

#: Collections a skill may add items to, with the item model used for validation.
ITEM_COLLECTIONS: dict[str, type[BaseModel]] = {
    "personas": Persona,
    "roles": Role,
    "functional_requirements": FunctionalRequirement,
    "nonfunctional_requirements": NonFunctionalRequirement,
    "acceptance_criteria": AcceptanceCriterion,
    "business_rules": BusinessRule,
    "entities": DataEntity,
    "screens": Screen,
    "assumptions": Assumption,
}

FactPath = Literal[
    "/objective", "/domain", "/security/classification", "/security/risk_level", "/accessibility/standard"
]
CollectionName = Literal[
    "personas",
    "roles",
    "functional_requirements",
    "nonfunctional_requirements",
    "acceptance_criteria",
    "business_rules",
    "entities",
    "screens",
    "assumptions",
]


class SetFact(_Strict):
    op: Literal["set_fact"] = "set_fact"
    proposal_id: Identifier
    path: FactPath
    value: str = Field(min_length=1, max_length=5000)
    rationale: ShortText | None = None


class AddItem(_Strict):
    op: Literal["add_item"] = "add_item"
    proposal_id: Identifier
    collection: CollectionName
    #: Item fields without status/provenance/revision, which apply_commands controls.
    item: dict[str, Any]
    rationale: ShortText | None = None


class AddOpenQuestion(_Strict):
    op: Literal["add_open_question"] = "add_open_question"
    proposal_id: Identifier
    question_id: Identifier
    question: LongText
    blocking: bool = False
    related_ids: list[Identifier] = Field(default_factory=list)


SpecCommand = Annotated[SetFact | AddItem | AddOpenQuestion, Field(discriminator="op")]


class Decision(StrEnum):
    ACCEPT = "accept"  # add to the spec as `proposed`
    CONFIRM = "confirm"  # add to the spec as `confirmed` by the deciding user
    REJECT = "reject"


class Outcome(StrEnum):
    APPLIED = "applied"
    REJECTED_BY_USER = "rejected_by_user"
    SKIPPED_CONFIRMED_FACT = "skipped_confirmed_fact"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    SKIPPED_ID_CONFLICT = "skipped_id_conflict"
    INVALID = "invalid"
    WOULD_BREAK_REFERENCES = "would_break_references"


class CommandResult(_Strict):
    proposal_id: str
    outcome: Outcome
    detail: str | None = None


_CONTROLLED_FIELDS = {"status", "provenance", "confirmed_by", "revision"}


def _status_fields(decision: Decision, actor: str) -> dict[str, Any]:
    if decision is Decision.CONFIRM:
        return {"status": "confirmed", "confirmed_by": actor}
    return {"status": "proposed", "confirmed_by": None}


def _error_count(spec: ApplicationSpec) -> int:
    return sum(1 for issue in validate_spec(spec) if issue.severity is Severity.ERROR)


def _apply_one(
    spec: ApplicationSpec,
    command: SetFact | AddItem | AddOpenQuestion,
    decision: Decision,
    provenance: Provenance,
    actor: str,
) -> tuple[ApplicationSpec | None, Outcome, str | None]:
    doc = spec.model_dump(mode="json")
    if isinstance(command, SetFact):
        node = doc
        for part in FACT_PATHS[command.path]:
            node = node[part]
        if node["status"] == FactStatus.CONFIRMED:
            return None, Outcome.SKIPPED_CONFIRMED_FACT, f"{command.path} is already confirmed"
        if node["value"] == command.value and node["status"] == FactStatus.PROPOSED and decision is Decision.ACCEPT:
            return None, Outcome.SKIPPED_DUPLICATE, "the same value is already proposed"
        node.update(
            {
                "value": command.value,
                "provenance": provenance.model_dump(mode="json"),
                **_status_fields(decision, actor),
            }
        )
    elif isinstance(command, AddItem):
        item = {k: v for k, v in command.item.items() if k not in _CONTROLLED_FIELDS}
        item_id = item.get("id")
        if any(existing.get("id") == item_id for existing in doc[command.collection]):
            return None, Outcome.SKIPPED_ID_CONFLICT, f"id '{item_id}' already exists"
        item.update({"provenance": provenance.model_dump(mode="json"), **_status_fields(decision, actor)})
        try:
            ITEM_COLLECTIONS[command.collection].model_validate(item)
        except ValidationError as exc:
            return None, Outcome.INVALID, str(exc.errors()[0].get("msg"))[:200]
        doc[command.collection].append(item)
    else:
        if any(q["question"].strip().lower() == command.question.strip().lower() for q in doc["open_questions"]):
            return None, Outcome.SKIPPED_DUPLICATE, "the same question is already open"
        if any(q["id"] == command.question_id for q in doc["open_questions"]):
            return None, Outcome.SKIPPED_ID_CONFLICT, f"id '{command.question_id}' already exists"
        question = OpenQuestion(
            id=command.question_id,
            question=command.question,
            blocking=command.blocking,
            related_ids=command.related_ids,
        )
        doc["open_questions"].append(question.model_dump(mode="json"))
    try:
        updated = ApplicationSpec.model_validate(doc)
    except ValidationError as exc:
        return None, Outcome.INVALID, str(exc.errors()[0].get("msg"))[:200]
    if _error_count(updated) > _error_count(spec):
        return None, Outcome.WOULD_BREAK_REFERENCES, "applying this would create a dangling reference"
    return updated, Outcome.APPLIED, None


def apply_commands(
    spec: ApplicationSpec,
    commands: list[SetFact | AddItem | AddOpenQuestion],
    decisions: dict[str, Decision],
    *,
    provenance: Provenance,
    actor: str,
) -> tuple[ApplicationSpec, list[CommandResult]]:
    """Apply decided commands in order. Commands without a decision are treated as rejected."""
    current = spec
    results: list[CommandResult] = []
    for command in commands:
        decision = decisions.get(command.proposal_id, Decision.REJECT)
        if decision is Decision.REJECT:
            results.append(CommandResult(proposal_id=command.proposal_id, outcome=Outcome.REJECTED_BY_USER))
            continue
        updated, outcome, detail = _apply_one(current, command, decision, provenance, actor)
        if updated is not None:
            current = updated
        results.append(CommandResult(proposal_id=command.proposal_id, outcome=outcome, detail=detail))
    return current, results
