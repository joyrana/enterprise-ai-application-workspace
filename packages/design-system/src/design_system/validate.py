"""Deterministic checks on a UI document: structure, accessibility rules and references.

Issues carry a JSON-pointer path into the document, a stable rule code and a
severity. ``error`` means a generator must not produce code from the document
as is; ``warning`` means a person should look (for example a placeholder for a
component the IR cannot express yet).

The accessibility rules encode WCAG-relevant structure that can be decided
from the IR alone (labels, heading order, table captions, one primary action).
They do not replace testing the rendered result (axe in the E2E suite).
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel

from appspec import ApplicationSpec

from .ir import Action, Form, Heading, Node, Placeholder, Section, Table, Toolbar, UiDocument, walk


class UiIssue(BaseModel):
    path: str
    code: str
    severity: Literal["error", "warning"]
    message: str


def _issue(path: str, code: str, message: str, severity: Literal["error", "warning"] = "error") -> UiIssue:
    return UiIssue(path=path, code=code, severity=severity, message=message)


def _action_ids(actions: list[Action], path: str) -> list[tuple[str, Action]]:
    return [(f"{path}/{i}", a) for i, a in enumerate(actions)]


def validate_document(doc: UiDocument, spec: ApplicationSpec | None = None) -> list[UiIssue]:
    issues: list[UiIssue] = []
    seen: Counter[str] = Counter()
    screen_ids = {s.id for s in doc.screens}
    routes = Counter(s.route for s in doc.screens)
    entity_ids = {e.id for e in spec.entities} if spec else None
    requirement_ids = {r.id for r in spec.functional_requirements} if spec else None
    persona_ids = {p.id for p in spec.personas} if spec else None

    for si, screen in enumerate(doc.screens):
        base = f"/screens/{si}"
        seen[screen.id] += 1
        if routes[screen.route] > 1:
            issues.append(
                _issue(f"{base}/route", "route-duplicate", f"Route {screen.route} is used by several screens.")
            )
        if requirement_ids is not None:
            for ri, rid in enumerate(screen.requirement_ids):
                if rid not in requirement_ids:
                    issues.append(
                        _issue(f"{base}/requirement_ids/{ri}", "ref-requirement", f"Unknown requirement {rid}.")
                    )
        if persona_ids is not None:
            for pi, pid in enumerate(screen.persona_ids):
                if pid not in persona_ids:
                    issues.append(_issue(f"{base}/persona_ids/{pi}", "ref-persona", f"Unknown persona {pid}."))

        nodes = walk(screen.body, f"{base}/body")
        headings = [(p, n) for p, n in nodes if isinstance(n, Heading)]
        h1 = [p for p, n in headings if n.level == 1]
        if len(h1) != 1:
            issues.append(
                _issue(f"{base}/body", "a11y-one-h1", f"A screen needs exactly one level-1 heading; found {len(h1)}.")
            )
        previous = 0
        for path, heading in headings:
            if previous and heading.level > previous + 1:
                issues.append(
                    _issue(
                        f"{path}/level",
                        "a11y-heading-order",
                        f"Heading level {heading.level} follows level {previous}; levels must not be skipped.",
                    )
                )
            previous = heading.level

        for path, node in nodes:
            seen[node.id] += 1
            issues.extend(_check_node(path, node, screen_ids, entity_ids, seen))

    for node_id, count in seen.items():
        if count > 1:
            issues.append(_issue("/screens", "id-duplicate", f"Id '{node_id}' is used {count} times."))
    return issues


def _check_node(
    path: str, node: Node, screen_ids: set[str], entity_ids: set[str] | None, seen: Counter[str]
) -> list[UiIssue]:
    issues: list[UiIssue] = []
    actions: list[tuple[str, Action]] = []
    if isinstance(node, Form):
        if not node.fields:
            issues.append(_issue(f"{path}/fields", "form-empty", "A form needs at least one field."))
        names = Counter(f.name for f in node.fields)
        for fi, field in enumerate(node.fields):
            fpath = f"{path}/fields/{fi}"
            seen[field.id] += 1
            if names[field.name] > 1:
                issues.append(_issue(f"{fpath}/name", "field-name-duplicate", f"Field name '{field.name}' repeats."))
            if field.input == "select" and not field.options and not field.options_from_entity:
                issues.append(_issue(f"{fpath}/options", "select-no-options", "A select needs options or a source."))
            if field.options_from_entity and entity_ids is not None and field.options_from_entity not in entity_ids:
                issues.append(
                    _issue(f"{fpath}/options_from_entity", "ref-entity", f"Unknown entity {field.options_from_entity}.")
                )
        primaries = [a for a in node.actions if a.intent == "primary"]
        if len(primaries) > 1:
            issues.append(_issue(f"{path}/actions", "form-one-primary", "A form may have at most one primary action."))
        if not any(a.action == "submit" for a in node.actions):
            issues.append(
                _issue(f"{path}/actions", "form-no-submit", "The form has no submit action.", severity="warning")
            )
        actions = _action_ids(node.actions, f"{path}/actions")
        if node.entity_id and entity_ids is not None and node.entity_id not in entity_ids:
            issues.append(_issue(f"{path}/entity_id", "ref-entity", f"Unknown entity {node.entity_id}."))
    elif isinstance(node, Table):
        if not node.columns:
            issues.append(_issue(f"{path}/columns", "table-no-columns", "A table needs at least one column."))
        keys = Counter(c.key for c in node.columns)
        for ci, column in enumerate(node.columns):
            if keys[column.key] > 1:
                issues.append(_issue(f"{path}/columns/{ci}/key", "column-duplicate", f"Column '{column.key}' repeats."))
        actions = _action_ids(node.row_actions, f"{path}/row_actions")
        if node.entity_id and entity_ids is not None and node.entity_id not in entity_ids:
            issues.append(_issue(f"{path}/entity_id", "ref-entity", f"Unknown entity {node.entity_id}."))
    elif isinstance(node, Toolbar):
        actions = _action_ids(node.actions, f"{path}/actions")
        if not node.actions:
            issues.append(_issue(f"{path}/actions", "toolbar-empty", "A toolbar needs at least one action."))
    elif isinstance(node, Placeholder):
        issues.append(
            _issue(
                path,
                "unsupported-component",
                f"'{node.requested_kind}' cannot be expressed in the IR yet: {node.reason}",
                severity="warning",
            )
        )
    elif isinstance(node, Section) and not node.children:
        issues.append(_issue(f"{path}/children", "section-empty", "An empty section.", severity="warning"))

    for apath, action in actions:
        seen[action.id] += 1
        if action.action == "edit-record" and action.target_screen not in screen_ids:
            issues.append(
                _issue(f"{apath}/target_screen", "ref-screen", f"Unknown edit screen {action.target_screen}.")
            )
        if action.action == "navigate":
            if not action.target_screen:
                issues.append(_issue(f"{apath}/target_screen", "navigate-no-target", "Navigation needs a target."))
            elif action.target_screen not in screen_ids:
                issues.append(
                    _issue(f"{apath}/target_screen", "ref-screen", f"Unknown target screen {action.target_screen}.")
                )
    return issues
