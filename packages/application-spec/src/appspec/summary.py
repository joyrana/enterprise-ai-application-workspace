"""Requirement-status summary used by the workspace overview.

Purely deterministic: it counts what is in the spec and never guesses.
"""

from __future__ import annotations

from pydantic import BaseModel

from .common import FactStatus, ItemStatus, Tracked
from .model import ApplicationSpec


class FactSummary(BaseModel):
    path: str
    label: str
    status: FactStatus


class CollectionSummary(BaseModel):
    name: str
    label: str
    proposed: int
    confirmed: int


class SpecSummary(BaseModel):
    facts: list[FactSummary]
    collections: list[CollectionSummary]
    open_questions: int
    blocking_questions: int
    confirmed_facts: int
    total_facts: int


_FACTS: tuple[tuple[str, str], ...] = (
    ("/objective", "Business objective"),
    ("/domain", "Application domain"),
    ("/framework/framework", "Framework"),
    ("/design_system/id", "Design system"),
    ("/design_system/version", "Design-system version"),
    ("/accessibility/standard", "Accessibility standard"),
    ("/security/classification", "Data classification"),
    ("/security/risk_level", "Risk level"),
)

_COLLECTIONS: tuple[tuple[str, str], ...] = (
    ("personas", "Personas"),
    ("roles", "Roles"),
    ("journeys", "User journeys"),
    ("functional_requirements", "Functional requirements"),
    ("nonfunctional_requirements", "Non-functional requirements"),
    ("acceptance_criteria", "Acceptance criteria"),
    ("business_rules", "Business rules"),
    ("entities", "Data entities"),
    ("integrations", "Integrations"),
    ("authorization", "Authorization rules"),
    ("screens", "Screens"),
    ("assumptions", "Assumptions"),
    ("decisions", "Decisions"),
)


def _resolve(spec: ApplicationSpec, path: str) -> Tracked[object]:
    node: object = spec
    for part in path.strip("/").split("/"):
        node = getattr(node, part)
    assert isinstance(node, Tracked)
    return node


def summarize(spec: ApplicationSpec) -> SpecSummary:
    facts = [FactSummary(path=p, label=label, status=_resolve(spec, p).status) for p, label in _FACTS]
    collections = []
    for name, label in _COLLECTIONS:
        items = getattr(spec, name)
        confirmed = sum(1 for item in items if item.status is ItemStatus.CONFIRMED)
        collections.append(
            CollectionSummary(name=name, label=label, proposed=len(items) - confirmed, confirmed=confirmed)
        )
    return SpecSummary(
        facts=facts,
        collections=collections,
        open_questions=len(spec.open_questions),
        blocking_questions=sum(1 for q in spec.open_questions if q.blocking),
        confirmed_facts=sum(1 for f in facts if f.status is FactStatus.CONFIRMED),
        total_facts=len(facts),
    )
