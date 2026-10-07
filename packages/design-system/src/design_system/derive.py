"""Deterministic derivation of the UI IR from the specification.

* Spec screens (``spec.screens``) become IR screens: a level-1 title, the purpose,
  and each semantic component mapped to an IR node. A component the IR cannot
  express (chart, dialog, tabs…) or that lacks the information to render (a table
  without an entity) becomes a ``placeholder`` with the reason, never a guess.
* With no spec screens yet, each data entity gets a list screen and a create
  form, labelled as derived from entities.

Same spec in, same IR out: no model is involved, so the IR can be recomputed for
any revision and diffed.
"""

from __future__ import annotations

from typing import Literal

from appspec import ApplicationSpec
from appspec.model import DataEntity, EntityField, FieldType
from appspec.model import FormField as SpecFormField
from appspec.model import Screen as SpecScreen

from .ir import (
    Action,
    Column,
    FieldValidation,
    Form,
    FormField,
    Heading,
    InputType,
    Message,
    Node,
    Placeholder,
    Screen,
    ScreenSource,
    Stat,
    Table,
    Text,
    Toolbar,
    UiDocument,
)

_INPUT: dict[FieldType, InputType] = {
    FieldType.STRING: "text",
    FieldType.TEXT: "textarea",
    FieldType.INTEGER: "number",
    FieldType.DECIMAL: "number",
    FieldType.MONEY: "number",
    FieldType.BOOLEAN: "checkbox",
    FieldType.DATE: "date",
    FieldType.DATETIME: "datetime",
    FieldType.ENUM: "select",
    FieldType.FILE: "file",
    FieldType.REFERENCE: "select",
}

_COLUMN = {
    FieldType.MONEY: "money",
    FieldType.INTEGER: "number",
    FieldType.DECIMAL: "number",
    FieldType.DATE: "date",
    FieldType.DATETIME: "date",
    FieldType.BOOLEAN: "boolean",
    FieldType.REFERENCE: "reference",
}

_NOT_IN_IR = {
    "chart": "charts are not part of IR v1",
    "dialog": "dialogs are not part of IR v1",
    "tabs": "tabs are not part of IR v1",
    "other": "the spec does not say what this component is",
}


def _id(*parts: str) -> str:
    return "-".join(p for p in parts if p)[:96].rstrip("-")


def humanize(name: str) -> str:
    words = name.replace("_", "-").split("-")
    text = " ".join(w for w in words if w)
    return text[:1].upper() + text[1:] if text else name


def _number_kind(field_type: FieldType) -> Literal["integer", "decimal"] | None:
    if field_type is FieldType.INTEGER:
        return "integer"
    if field_type in (FieldType.DECIMAL, FieldType.MONEY):
        return "decimal"
    return None


def _entity_field(prefix: str, field: EntityField) -> FormField:
    return FormField(
        id=_id(prefix, field.name),
        name=field.name,
        label=humanize(field.name),
        input=_INPUT[field.type],
        required=field.required,
        help_text=field.description,
        options=list(field.enum_values) if field.type is FieldType.ENUM else [],
        options_from_entity=field.reference_entity_id if field.type is FieldType.REFERENCE else None,
        number_kind=_number_kind(field.type),
    )


def _spec_field(prefix: str, field: SpecFormField) -> FormField:
    return FormField(
        id=_id(prefix, field.name),
        name=field.name,
        label=field.label,
        input=_INPUT[field.type],
        required=field.required,
        help_text=field.help_text,
        validation=[FieldValidation(kind=v.kind, value=v.value, message=v.message) for v in field.validation],
        number_kind=_number_kind(field.type),
    )


def _columns(entity: DataEntity) -> list[Column]:
    return [Column(key=f.name, label=humanize(f.name), type=_COLUMN.get(f.type, "text")) for f in entity.fields]


def _form_actions(prefix: str, cancel_target: str | None) -> list[Action]:
    cancel = (
        Action(id=_id(prefix, "cancel"), label="Cancel", action="navigate", target_screen=cancel_target)
        if cancel_target
        else Action(id=_id(prefix, "cancel"), label="Cancel", action="cancel")
    )
    return [Action(id=_id(prefix, "save"), label="Save", intent="primary", action="submit"), cancel]


def _spec_screen(screen: SpecScreen, entities: dict[str, DataEntity]) -> Screen:
    body: list[Node] = [Heading(id=_id(screen.id, "title"), text=screen.name, level=1)]
    if screen.purpose:
        body.append(Text(id=_id(screen.id, "purpose"), text=screen.purpose, tone="subtle"))
    fields_used = False
    for component in screen.components:
        cid = _id(screen.id, component.id)
        entity = entities.get(component.entity_id) if component.entity_id else None
        missing_entity = component.entity_id is not None and entity is None
        if component.kind in _NOT_IN_IR:
            body.append(
                Placeholder(
                    id=cid, requested_kind=component.kind, label=component.label, reason=_NOT_IN_IR[component.kind]
                )
            )
        elif missing_entity:
            body.append(
                Placeholder(
                    id=cid,
                    requested_kind=component.kind,
                    label=component.label,
                    reason=f"entity '{component.entity_id}' is not in the specification",
                )
            )
        elif component.kind in ("table", "list"):
            if entity is None:
                body.append(
                    Placeholder(
                        id=cid,
                        requested_kind=component.kind,
                        label=component.label,
                        reason="a table needs an entity to know its columns",
                    )
                )
            else:
                body.append(
                    Table(
                        id=cid,
                        caption=component.label or entity.name,
                        entity_id=entity.id,
                        columns=_columns(entity),
                        empty_text=f"No {entity.name.lower()} records yet.",
                    )
                )
        elif component.kind == "form":
            if entity is not None:
                fields = [_entity_field(cid, f) for f in entity.fields]
            elif screen.fields:
                fields = [_spec_field(cid, f) for f in screen.fields]
                fields_used = True
            else:
                fields = []
            if not fields:
                body.append(
                    Placeholder(
                        id=cid,
                        requested_kind="form",
                        label=component.label,
                        reason="the form's fields are not specified",
                    )
                )
            else:
                body.append(
                    Form(
                        id=cid,
                        label=component.label or (entity.name if entity else screen.name),
                        entity_id=entity.id if entity else None,
                        fields=fields,
                        actions=_form_actions(cid, None),
                    )
                )
        elif component.kind == "metric":
            body.append(Stat(id=cid, label=component.label or "Metric"))
        elif component.kind == "notification":
            body.append(Message(id=cid, intent="info", title=component.label or "Notification"))
        elif component.kind == "text" and component.label:
            body.append(Text(id=cid, text=component.label))
        else:  # card, toolbar, or text without content
            body.append(
                Placeholder(
                    id=cid,
                    requested_kind=component.kind,
                    label=component.label,
                    reason=f"the {component.kind}'s content is not specified",
                )
            )
    if screen.fields and not fields_used:
        fid = _id(screen.id, "form")
        body.append(
            Form(
                id=fid,
                label=screen.name,
                fields=[_spec_field(fid, f) for f in screen.fields],
                actions=_form_actions(fid, None),
            )
        )
    return Screen(
        id=screen.id,
        title=screen.name,
        route=f"/{screen.id}",
        source=ScreenSource(kind="spec-screen", ref=screen.id),
        requirement_ids=list(screen.requirement_ids),
        persona_ids=list(screen.persona_ids),
        body=body,
    )


def _entity_screens(entity: DataEntity) -> list[Screen]:
    list_id, form_id = _id(entity.id, "list"), _id(entity.id, "form")
    note = Text(
        id=_id(list_id, "note"),
        text="Derived from the data entity because the specification has no screens yet.",
        tone="subtle",
    )
    list_screen = Screen(
        id=list_id,
        title=entity.name,
        route=f"/{entity.id}",
        source=ScreenSource(kind="entity-list", ref=entity.id),
        body=[
            Heading(id=_id(list_id, "title"), text=entity.name, level=1),
            note,
            Toolbar(
                id=_id(list_id, "toolbar"),
                label=f"{entity.name} actions",
                actions=[
                    Action(
                        id=_id(list_id, "new"),
                        label=f"New {entity.name.lower()}",
                        intent="primary",
                        action="navigate",
                        target_screen=form_id,
                    )
                ],
            ),
            Table(
                id=_id(list_id, "table"),
                caption=entity.name,
                entity_id=entity.id,
                columns=_columns(entity),
                empty_text=f"No {entity.name.lower()} records yet.",
                row_actions=[
                    Action(id=_id(list_id, "edit"), label="Edit", action="edit-record", target_screen=form_id),
                    Action(id=_id(list_id, "delete"), label="Delete", intent="danger", action="delete-record"),
                ],
            )
            if entity.fields
            else Placeholder(
                id=_id(list_id, "table"), requested_kind="table", reason="the entity has no fields to show as columns"
            ),
        ],
    )
    form_body: list[Node] = [Heading(id=_id(form_id, "title"), text=f"New {entity.name.lower()}", level=1)]
    if entity.fields:
        form_body.append(
            Form(
                id=_id(form_id, "form"),
                label=f"New {entity.name.lower()}",
                entity_id=entity.id,
                fields=[_entity_field(_id(form_id, "form"), f) for f in entity.fields],
                actions=_form_actions(_id(form_id, "form"), list_id),
            )
        )
    else:
        form_body.append(
            Placeholder(id=_id(form_id, "form"), requested_kind="form", reason="the entity has no fields yet")
        )
    form_screen = Screen(
        id=form_id,
        title=f"New {entity.name.lower()}",
        route=f"/{entity.id}/new",
        source=ScreenSource(kind="entity-form", ref=entity.id),
        body=form_body,
    )
    return [list_screen, form_screen]


def derive_document(spec: ApplicationSpec, spec_revision: int | None = None) -> UiDocument:
    entities = {e.id: e for e in spec.entities}
    if spec.screens:
        screens = [_spec_screen(s, entities) for s in spec.screens]
    else:
        screens = [s for e in spec.entities for s in _entity_screens(e)]
    return UiDocument(spec_revision=spec_revision, screens=screens)
