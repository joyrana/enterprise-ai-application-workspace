"""Deterministic semantic validation that structural (Pydantic) validation cannot express.

Structural validation answers "is this well-formed?". Semantic validation
answers "does it hang together?" — mainly referential integrity between
sections. Issues carry a JSON-pointer-like path so the UI can highlight them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from enum import StrEnum

from pydantic import BaseModel

from .model import ID_COLLECTIONS, ApplicationSpec, NavigationItem


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    code: str
    severity: Severity
    path: str
    message: str


def _ids(items: Iterable[object]) -> set[str]:
    return {item.id for item in items}  # type: ignore[attr-defined]


def _walk_nav(nodes: list[NavigationItem], prefix: str) -> Iterator[tuple[str, NavigationItem]]:
    for i, node in enumerate(nodes):
        path = f"{prefix}/{i}"
        yield path, node
        yield from _walk_nav(node.children, f"{path}/children")


def validate_spec(spec: ApplicationSpec) -> list[ValidationIssue]:
    """Return referential-integrity errors and completeness warnings, in a stable order."""
    issues: list[ValidationIssue] = []

    def ref(path: str, target: str, known: set[str], kind: str) -> None:
        if target not in known:
            issues.append(
                ValidationIssue(
                    code="dangling-reference",
                    severity=Severity.ERROR,
                    path=path,
                    message=f"references unknown {kind} '{target}'",
                )
            )

    personas = _ids(spec.personas)
    roles = _ids(spec.roles)
    requirements = _ids(spec.functional_requirements)
    entities = _ids(spec.entities)
    screens = _ids(spec.screens)
    all_ids: set[str] = set()
    for collection in ID_COLLECTIONS:
        all_ids |= _ids(getattr(spec, collection))
    nav_paths = list(_walk_nav(spec.navigation, "/navigation"))
    all_ids |= {node.id for _, node in nav_paths}

    for i, p in enumerate(spec.personas):
        for j, r in enumerate(p.role_ids):
            ref(f"/personas/{i}/role_ids/{j}", r, roles, "role")
    for i, jn in enumerate(spec.journeys):
        for j, pid in enumerate(jn.persona_ids):
            ref(f"/journeys/{i}/persona_ids/{j}", pid, personas, "persona")
        for j, step in enumerate(jn.steps):
            if step.screen_id is not None:
                ref(f"/journeys/{i}/steps/{j}/screen_id", step.screen_id, screens, "screen")
    for i, fr in enumerate(spec.functional_requirements):
        for j, pid in enumerate(fr.persona_ids):
            ref(f"/functional_requirements/{i}/persona_ids/{j}", pid, personas, "persona")
    for i, ac in enumerate(spec.acceptance_criteria):
        ref(f"/acceptance_criteria/{i}/requirement_id", ac.requirement_id, requirements, "functional requirement")
    for i, br in enumerate(spec.business_rules):
        for j, rid in enumerate(br.requirement_ids):
            ref(f"/business_rules/{i}/requirement_ids/{j}", rid, requirements, "functional requirement")
    for i, ent in enumerate(spec.entities):
        for j, field in enumerate(ent.fields):
            if field.reference_entity_id is not None:
                ref(f"/entities/{i}/fields/{j}/reference_entity_id", field.reference_entity_id, entities, "entity")
        for j, rel in enumerate(ent.relationships):
            ref(f"/entities/{i}/relationships/{j}/target_entity_id", rel.target_entity_id, entities, "entity")
    for i, integ in enumerate(spec.integrations):
        for j, eid in enumerate(integ.entity_ids):
            ref(f"/integrations/{i}/entity_ids/{j}", eid, entities, "entity")
    for i, rule in enumerate(spec.authorization):
        ref(f"/authorization/{i}/role_id", rule.role_id, roles, "role")
    for path, node in nav_paths:
        if node.screen_id is not None:
            ref(f"{path}/screen_id", node.screen_id, screens, "screen")
    for i, sc in enumerate(spec.screens):
        for j, pid in enumerate(sc.persona_ids):
            ref(f"/screens/{i}/persona_ids/{j}", pid, personas, "persona")
        for j, rid in enumerate(sc.requirement_ids):
            ref(f"/screens/{i}/requirement_ids/{j}", rid, requirements, "functional requirement")
        for j, comp in enumerate(sc.components):
            if comp.entity_id is not None:
                ref(f"/screens/{i}/components/{j}/entity_id", comp.entity_id, entities, "entity")
    for name in ("assumptions", "open_questions", "decisions"):
        for i, item in enumerate(getattr(spec, name)):
            for j, rid in enumerate(item.related_ids):
                ref(f"/{name}/{i}/related_ids/{j}", rid, all_ids, "element")
    for i, dep in enumerate(spec.artifact_dependencies):
        ref(f"/artifact_dependencies/{i}/from_id", dep.from_id, all_ids, "element")
        ref(f"/artifact_dependencies/{i}/to_id", dep.to_id, all_ids, "element")

    # Completeness warnings: never block saving, but surface gaps honestly.
    covered = {ac.requirement_id for ac in spec.acceptance_criteria}
    for i, fr in enumerate(spec.functional_requirements):
        if fr.id not in covered:
            issues.append(
                ValidationIssue(
                    code="requirement-without-acceptance-criteria",
                    severity=Severity.WARNING,
                    path=f"/functional_requirements/{i}",
                    message=f"requirement '{fr.id}' has no acceptance criteria",
                )
            )
    return issues


def has_errors(issues: Iterable[ValidationIssue]) -> bool:
    return any(issue.severity is Severity.ERROR for issue in issues)
