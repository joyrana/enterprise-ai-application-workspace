"""Organization policies (ADR-0018).

A policy set is typed, versioned data that an organization admin maintains. Each rule is one
of a fixed set of kinds, evaluated deterministically against the specification and the UI IR.
No rule runs code supplied by the organization, and no model decides compliance. ``error``
findings block code generation and builds; ``warning`` findings are shown.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from appspec import ApplicationSpec
from appspec.common import ItemStatus
from design_system import UiDocument
from design_system.ir import Form, Table, walk

POLICY_VERSION: Literal["1"] = "1"
RuleId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
Severity = Literal["error", "warning"]
_CLASSIFICATION_ORDER = ["public", "internal", "confidential", "restricted"]
_FRAMEWORKS = ("react", "angular")


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: RuleId
    severity: Severity = "error"
    description: str | None = Field(default=None, max_length=300)


class AllowedFrameworks(_Rule):
    kind: Literal["allowed-frameworks"] = "allowed-frameworks"
    frameworks: list[Literal["react", "angular"]] = Field(min_length=1)


class AllowedDesignSystems(_Rule):
    kind: Literal["allowed-design-systems"] = "allowed-design-systems"
    ids: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9:-]{1,60}$")]] = Field(min_length=1)


class ForbiddenComponents(_Rule):
    kind: Literal["forbidden-components"] = "forbidden-components"
    #: IR constructs, e.g. "field:file", "stat", "table".
    constructs: list[Annotated[str, Field(pattern=r"^[a-z]+(:[a-z0-9]+)?$")]] = Field(min_length=1)


class MaxFormFields(_Rule):
    kind: Literal["max-form-fields"] = "max-form-fields"
    max: int = Field(ge=1, le=200)


class AcceptanceCriteriaRequired(_Rule):
    kind: Literal["acceptance-criteria-required"] = "acceptance-criteria-required"


class ConfirmedRequirementsOnly(_Rule):
    kind: Literal["confirmed-requirements-only"] = "confirmed-requirements-only"


class SensitiveFields(_Rule):
    """Fields whose names look sensitive need the project classified at least ``minimum``."""

    kind: Literal["sensitive-fields"] = "sensitive-fields"
    name_patterns: list[Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")]] = Field(
        min_length=1, max_length=50
    )
    minimum: Literal["internal", "confidential", "restricted"] = "confidential"


class EntityNaming(_Rule):
    kind: Literal["entity-naming"] = "entity-naming"
    #: A regular expression every entity id must match. Kept short; ids are at most 64 characters.
    pattern: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"not a valid regular expression: {exc}") from exc
        return value


class RequiredScreenStates(_Rule):
    kind: Literal["required-screen-states"] = "required-screen-states"
    states: list[Literal["loading", "empty", "error", "success"]] = Field(min_length=1)


Rule = Annotated[
    AllowedFrameworks
    | AllowedDesignSystems
    | ForbiddenComponents
    | MaxFormFields
    | AcceptanceCriteriaRequired
    | ConfirmedRequirementsOnly
    | SensitiveFields
    | EntityNaming
    | RequiredScreenStates,
    Field(discriminator="kind"),
]


class PolicySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    policy_version: Literal["1"] = POLICY_VERSION
    rules: list[Rule] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _unique_ids(self) -> PolicySet:
        ids = [r.id for r in self.rules]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"rule ids must be unique (duplicated: {', '.join(duplicates)})")
        return self


class PolicyFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str
    kind: str
    severity: Severity
    path: str
    message: str


def _construct(node: object) -> str | None:
    kind = getattr(node, "kind", None)
    if kind == "heading":
        return f"heading:{getattr(node, 'level', '')}"
    if kind == "text":
        return f"text:{getattr(node, 'tone', 'default')}"
    if kind == "field":
        return f"field:{getattr(node, 'input', '')}"
    if kind == "action":
        return f"action:{getattr(node, 'intent', '')}"
    return str(kind) if kind else None


def _walk(document: UiDocument) -> Iterator[tuple[str, object]]:
    for i, screen in enumerate(document.screens):
        for path, node in walk(screen.body, f"/screens/{i}/body"):
            yield path, node
            if isinstance(node, Form):
                for j, field in enumerate(node.fields):
                    yield f"{path}/fields/{j}", field
                for j, action in enumerate(node.actions):
                    yield f"{path}/actions/{j}", action
            if isinstance(node, Table):
                for j, action in enumerate(node.row_actions):
                    yield f"{path}/row_actions/{j}", action


def evaluate(
    policy: PolicySet, spec: ApplicationSpec, document: UiDocument, design_system_id: str
) -> list[PolicyFinding]:
    """Every finding of every rule, in rule order then document order. Pure and deterministic."""
    findings: list[PolicyFinding] = []
    for rule in policy.rules:

        def found(path: str, message: str, rule: _Rule = rule) -> None:
            findings.append(
                PolicyFinding(
                    rule_id=rule.id,
                    kind=getattr(rule, "kind", ""),
                    severity=rule.severity,
                    path=path,
                    message=message,
                )
            )

        if isinstance(rule, AllowedFrameworks):
            framework = spec.framework.framework.value
            value = framework.value if framework is not None else None
            if value is not None and value not in rule.frameworks:
                found("/framework/framework", f"{value} is not an allowed framework ({', '.join(rule.frameworks)}).")
        elif isinstance(rule, AllowedDesignSystems):
            if design_system_id not in rule.ids:
                found(
                    "/design_system/id", f"Design system '{design_system_id}' is not allowed ({', '.join(rule.ids)})."
                )
        elif isinstance(rule, ForbiddenComponents):
            forbidden = set(rule.constructs)
            for path, node in _walk(document):
                construct = _construct(node)
                if construct in forbidden or (construct and construct.split(":")[0] in forbidden):
                    found(path, f"'{construct}' is not allowed by organization policy.")
        elif isinstance(rule, MaxFormFields):
            for path, node in _walk(document):
                if isinstance(node, Form) and len(node.fields) > rule.max:
                    found(path, f"Form '{node.label}' has {len(node.fields)} fields; the limit is {rule.max}.")
        elif isinstance(rule, AcceptanceCriteriaRequired):
            covered = {c.requirement_id for c in spec.acceptance_criteria}
            for i, req in enumerate(spec.functional_requirements):
                if req.id not in covered:
                    found(f"/functional_requirements/{i}", f"Requirement '{req.title}' has no acceptance criteria.")
        elif isinstance(rule, ConfirmedRequirementsOnly):
            for i, req in enumerate(spec.functional_requirements):
                if req.status is not ItemStatus.CONFIRMED:
                    found(f"/functional_requirements/{i}", f"Requirement '{req.title}' is not confirmed yet.")
        elif isinstance(rule, SensitiveFields):
            classification = spec.security.classification.value
            level = _CLASSIFICATION_ORDER.index(classification.value) if classification is not None else -1
            needed = _CLASSIFICATION_ORDER.index(rule.minimum)
            if level < needed:
                for i, entity in enumerate(spec.entities):
                    for j, field in enumerate(entity.fields):
                        name = field.name.lower()
                        if any(p in name for p in rule.name_patterns):
                            current = classification.value if classification is not None else "unclassified"
                            found(
                                f"/entities/{i}/fields/{j}",
                                f"Field '{entity.id}.{field.name}' looks sensitive; the project must be classified "
                                f"at least '{rule.minimum}' (it is {current}).",
                            )
        elif isinstance(rule, EntityNaming):
            pattern = re.compile(rule.pattern)
            for i, entity in enumerate(spec.entities):
                if not pattern.fullmatch(entity.id):
                    found(f"/entities/{i}/id", f"Entity id '{entity.id}' does not match /{rule.pattern}/.")
        elif isinstance(rule, RequiredScreenStates):
            for i, screen in enumerate(spec.screens):
                missing = [s for s in rule.states if s not in {state.value for state in screen.states}]
                if missing:
                    found(f"/screens/{i}/states", f"Screen '{screen.name}' does not define: {', '.join(missing)}.")
    return findings


def blocking(findings: list[PolicyFinding]) -> list[PolicyFinding]:
    return [f for f in findings if f.severity == "error"]


__all__ = [
    "POLICY_VERSION",
    "PolicyFinding",
    "PolicySet",
    "Rule",
    "blocking",
    "evaluate",
]
