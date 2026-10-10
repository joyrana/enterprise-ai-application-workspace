"""Change-impact preview: what a candidate specification would do to the app (Milestone 5).

Before saving a change, a person can see:
- which entities and screens it adds, removes or changes;
- which generated files change, and by how many lines;
- whether anything would block code generation.

Nothing is saved. Both sides are generated with the same revision number, so the file diff shows
only real changes (no provenance-header noise).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from appspec import ApplicationSpec, Severity, validate_spec
from codegen_angular import generate_project as generate_angular
from codegen_react import GeneratedProject, GenerationBlocked, diff_projects, generate_project
from design_system import derive_document, validate_document

from . import org, service, themes, ui
from .auth import Principal
from .schemas import ImpactFile, ImpactReport, NamedChanges


def _content(value: Any) -> Any:
    """Drop server-stamped revision metadata, which says when an element changed, not what it is."""
    if isinstance(value, dict):
        return {k: _content(v) for k, v in value.items() if k != "revision"}
    if isinstance(value, list):
        return [_content(v) for v in value]
    return value


def _by_id(items: list[Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): _content(item) for item in items if isinstance(item, dict) and "id" in item}


def _changes(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]], name_key: str) -> NamedChanges:
    def label(item: dict[str, Any], key: str) -> str:
        value = item.get(name_key) or key
        if isinstance(value, dict):  # tracked values carry {"value": ...}
            value = value.get("value") or key
        return str(value)

    return NamedChanges(
        added=sorted(label(after[k], k) for k in after.keys() - before.keys()),
        removed=sorted(label(before[k], k) for k in before.keys() - after.keys()),
        changed=sorted(label(after[k], k) for k in after.keys() & before.keys() if after[k] != before[k]),
    )


def _generate(spec: ApplicationSpec, contract: Any, revision: int, theme: Any) -> GeneratedProject:
    generate = generate_angular if contract.framework == "angular" else generate_project
    return generate(spec, contract, spec_revision=revision, theme=theme)


def preview(session: Session, principal: Principal, project_id: uuid.UUID, candidate: ApplicationSpec) -> ImpactReport:
    project = service.find_project(session, principal, project_id)
    number = project.current_revision
    current = service.spec_at(session, project, number)
    spec_issues = validate_spec(candidate)
    spec_valid = not any(i.severity is Severity.ERROR for i in spec_issues)

    before_dump = current.model_dump(mode="json")
    after_dump = candidate.model_dump(mode="json")
    entities = _changes(_by_id(before_dump.get("entities", [])), _by_id(after_dump.get("entities", [])), "name")
    report = ImpactReport(
        base_revision=number,
        spec_valid=spec_valid,
        spec_issues=spec_issues,
        entities=entities,
        screens=NamedChanges(added=[], removed=[], changed=[]),
        files=[],
        generation_blocked=False,
        ui_issues=[],
        note=None,
    )
    if not spec_valid:
        report.note = "The candidate specification has errors; fix them to see the effect on screens and code."
        return report

    preview_revision = number + 1
    _, _, report.policy_findings = org.findings_for(session, principal.tenant_id, candidate, preview_revision)
    if any(f.severity == "error" for f in report.policy_findings):
        report.generation_blocked = True
    before_doc = derive_document(current, spec_revision=preview_revision)
    after_doc = derive_document(candidate, spec_revision=preview_revision)
    screens_before = {s.id: s.model_dump(mode="json", exclude={"source"}) for s in before_doc.screens}
    screens_after = {s.id: s.model_dump(mode="json", exclude={"source"}) for s in after_doc.screens}
    report.screens = _changes(screens_before, screens_after, "title")
    report.ui_issues = [i for i in validate_document(after_doc, candidate) if i.severity == "error"]
    if report.ui_issues:
        report.generation_blocked = True
        report.note = "These changes would block code generation until the screen errors are fixed."
        return report

    org_themes = themes.themes_for(session, principal.tenant_id)
    contract_after, _, theme_after = ui.resolve(candidate, org_themes)
    try:
        contract_before, _, theme_before = ui.resolve(current, org_themes)
        before = _generate(current, contract_before, preview_revision, theme_before)
    except (GenerationBlocked, ui.DesignSystemUnavailable):
        report.note = f"Revision r{number} does not generate code, so there is no file-level comparison."
        return report
    after = _generate(candidate, contract_after, preview_revision, theme_after)
    report.files = [
        ImpactFile(path=d.path, status=d.status, additions=d.additions, deletions=d.deletions)
        for d in diff_projects(before, after)
    ]
    return report
