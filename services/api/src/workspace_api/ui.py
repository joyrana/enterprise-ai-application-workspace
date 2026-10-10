"""UI preview: derive the IR from a spec revision, validate it and render it with a design system (ADR-0013).

Nothing is stored: the IR is a pure function of the spec revision, so it is
recomputed on request and always matches the revision it names.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from appspec import ApplicationSpec
from appspec.model import Framework
from design_system import (
    DesignSystemContract,
    builtin_contracts,
    derive_document,
    get_contract,
    has_adapter,
    render_screens,
    validate_document,
)

from . import service
from .auth import Principal
from .errors import AppError, NotFound
from .schemas import DesignSystemChoice, DesignSystemList, DesignSystemSummary, UiPreview

DEFAULT_FOR_FRAMEWORK = {Framework.REACT: "fluent2", Framework.ANGULAR: "material3"}


class DesignSystemUnavailable(AppError):
    status, code, title = 422, "design-system-unavailable", "No usable design system for this project"


def list_design_systems() -> DesignSystemList:
    return DesignSystemList(
        items=[
            DesignSystemSummary(
                id=c.id,
                name=c.name,
                version=c.version,
                framework=c.framework,
                library_package=c.library.package,
                library_version=c.library.version,
                has_adapter=has_adapter(c.id),
            )
            for c in builtin_contracts().values()
        ]
    )


def get_design_system(contract_id: str) -> DesignSystemContract:
    contract = get_contract(contract_id)
    if contract is None:
        raise NotFound(f"Design system '{contract_id}' was not found.")
    return contract


def choose(spec: ApplicationSpec) -> tuple[DesignSystemContract, DesignSystemChoice]:
    framework = spec.framework.framework.value
    selected = spec.design_system.id.value
    if selected:
        contract = get_contract(selected)
        if contract is None:
            available = ", ".join(sorted(builtin_contracts()))
            raise DesignSystemUnavailable(
                f"The spec selects '{selected}', which is not available (built in: {available})."
            )
        if framework is not None and contract.framework != framework.value:
            raise DesignSystemUnavailable(
                f"The spec selects {contract.name}, a {contract.framework} design system, "
                f"but the app's framework is {framework.value}."
            )
        return contract, DesignSystemChoice(id=contract.id, version=contract.version, selected_by="spec", note=None)
    if framework is not None and framework not in DEFAULT_FOR_FRAMEWORK:
        raise DesignSystemUnavailable(f"No design system is available for {framework.value} yet.")
    default_id = DEFAULT_FOR_FRAMEWORK.get(framework, "fluent2") if framework is not None else "fluent2"
    contract = get_contract(default_id)
    assert contract is not None
    if framework is None:
        note = "The spec selects no framework or design system; previewing with Fluent 2 (React) as an assumption."
    elif default_id == "fluent2":
        note = "The spec selects no design system; Fluent 2 is the default for React."
    else:
        note = "The spec selects no design system; Material 3 is the default for Angular."
    return contract, DesignSystemChoice(id=contract.id, version=contract.version, selected_by="default", note=note)


def preview(session: Session, principal: Principal, project_id: uuid.UUID, revision: int | None) -> UiPreview:
    project = service.find_project(session, principal, project_id)
    number = project.current_revision if revision is None else revision
    spec = service.spec_at(session, project, number)
    contract, choice = choose(spec)
    document = derive_document(spec, spec_revision=number)
    rendered = render_screens(document.screens, contract) if has_adapter(contract.id) else []
    if not has_adapter(contract.id):
        extra = f"{contract.name} has no in-browser preview yet; the generated code is in the Code tab."
        choice = choice.model_copy(update={"note": f"{choice.note} {extra}" if choice.note else extra})
    return UiPreview(
        spec_revision=number,
        design_system=choice,
        document=document,
        issues=validate_document(document, spec),
        rendered=rendered,
    )
