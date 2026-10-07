"""UI intermediate representation (IR), version 1 (ADR-0013).

A framework-neutral, strictly typed description of screens. It says *what* a
screen contains (a form with these fields, a table with these columns, one
primary action), never *how* a library renders it. Design-system adapters map
IR nodes to concrete components; code generators (Milestone 4) consume the
adapter's output.

The IR is derived from the specification deterministically (``derive.py``), so
the spec stays the single source of truth (ADR-0002). Every node has an ``id``
unique within its document, so issues, previews and later code can point back
to it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

IR_VERSION: Literal["1"] = "1"

NodeId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,95}$")]
Label = Annotated[str, Field(min_length=1, max_length=200)]


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NodeId


class Heading(_Node):
    kind: Literal["heading"] = "heading"
    text: Label
    level: int = Field(ge=1, le=4)


class Text(_Node):
    kind: Literal["text"] = "text"
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    tone: Literal["default", "subtle"] = "default"


InputType = Literal["text", "textarea", "number", "date", "datetime", "select", "checkbox", "file"]


class FieldValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["required", "min", "max", "min-length", "max-length", "pattern", "custom"]
    value: str | float | None = None
    message: str | None = Field(default=None, max_length=200)


class FormField(_Node):
    kind: Literal["field"] = "field"
    name: Annotated[str, Field(min_length=1, max_length=96)]
    label: Label
    input: InputType
    required: bool = False
    help_text: str | None = Field(default=None, max_length=300)
    options: list[Label] = Field(default_factory=list, max_length=100)
    #: For ``select`` inputs whose options come from another entity at runtime.
    options_from_entity: str | None = None
    #: For ``number`` inputs: integers only, or any decimal (money, decimal). Additive in IR v1.
    number_kind: Literal["integer", "decimal"] | None = None
    validation: list[FieldValidation] = Field(default_factory=list)


class Action(_Node):
    kind: Literal["action"] = "action"
    label: Label
    intent: Literal["primary", "secondary", "danger"] = "secondary"
    action: Literal["submit", "cancel", "navigate", "custom"] = "custom"
    target_screen: str | None = None


class Form(_Node):
    kind: Literal["form"] = "form"
    label: Label
    entity_id: str | None = None
    fields: list[FormField] = Field(default_factory=list, max_length=60)
    actions: list[Action] = Field(default_factory=list, max_length=6)


class Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: Annotated[str, Field(min_length=1, max_length=96)]
    label: Label
    type: Literal["text", "number", "money", "date", "boolean", "reference"] = "text"


class Table(_Node):
    kind: Literal["table"] = "table"
    caption: Label
    entity_id: str | None = None
    columns: list[Column] = Field(default_factory=list, max_length=30)
    empty_text: Label = "Nothing here yet."
    row_actions: list[Action] = Field(default_factory=list, max_length=4)


class Stat(_Node):
    kind: Literal["stat"] = "stat"
    label: Label
    value_hint: str = Field(default="—", max_length=60)


class Message(_Node):
    kind: Literal["message"] = "message"
    intent: Literal["info", "warning", "error", "success"] = "info"
    title: Label
    text: str | None = Field(default=None, max_length=500)


class Toolbar(_Node):
    kind: Literal["toolbar"] = "toolbar"
    label: Label
    actions: list[Action] = Field(default_factory=list, max_length=8)


class Placeholder(_Node):
    """Something the spec asks for that the IR cannot express yet. Never silently dropped."""

    kind: Literal["placeholder"] = "placeholder"
    requested_kind: str = Field(max_length=40)
    label: str | None = Field(default=None, max_length=200)
    reason: str = Field(max_length=300)


class Section(_Node):
    kind: Literal["section"] = "section"
    title: Label | None = None
    children: list[Node] = Field(default_factory=list, max_length=40)


Node = Annotated[
    Heading | Text | Form | Table | Stat | Message | Toolbar | Placeholder | Section,
    Field(discriminator="kind"),
]
Section.model_rebuild()


class ScreenSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["spec-screen", "entity-list", "entity-form"]
    #: The spec screen id or entity id this screen was derived from.
    ref: str


class Screen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: NodeId
    title: Label
    route: Annotated[str, Field(pattern=r"^/[a-z0-9/-]*$", max_length=200)]
    source: ScreenSource
    requirement_ids: list[str] = Field(default_factory=list)
    persona_ids: list[str] = Field(default_factory=list)
    body: list[Node] = Field(default_factory=list, max_length=60)


class UiDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ir_version: Literal["1"] = IR_VERSION
    spec_revision: int | None = None
    screens: list[Screen] = Field(default_factory=list, max_length=100)


def json_schema() -> dict[str, object]:
    schema = UiDocument.model_json_schema()
    schema["$id"] = "urn:workspace:ui-ir:1"
    schema["title"] = "UI intermediate representation v1"
    return schema


def walk(nodes: list[Node], path: str) -> list[tuple[str, Node]]:
    """Every node with its JSON-pointer path, depth first (form fields and actions included)."""
    out: list[tuple[str, Node]] = []
    for i, node in enumerate(nodes):
        here = f"{path}/{i}"
        out.append((here, node))
        if isinstance(node, Section):
            out.extend(walk(node.children, f"{here}/children"))
    return out
