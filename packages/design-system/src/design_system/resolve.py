"""Adapters: map a UI document onto a design system's components.

The output is a *render tree*: component names from the contract, plain JSON
props and text. It is data, not code — the workspace previews it with an
allowlisted interpreter, and the Milestone 4 generator will print it as source.
Component names always come from the contract's mappings, so the contract,
adapter and preview cannot drift apart silently (tests check this).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from pydantic import BaseModel, Field

from .contract import DesignSystemContract
from .ir import (
    Action,
    Form,
    FormField,
    Heading,
    Message,
    Node,
    Placeholder,
    Screen,
    Section,
    Stat,
    Table,
    Text,
    Toolbar,
)

Prop = str | int | bool


class RenderNode(BaseModel):
    component: str
    props: dict[str, Prop] = Field(default_factory=dict)
    text: str | None = None
    children: list[RenderNode] = Field(default_factory=list)
    #: The IR node this element renders, for tracing issues and later code back to the IR.
    ir_id: str | None = None


class RenderedScreen(BaseModel):
    screen_id: str
    title: str
    route: str
    root: list[RenderNode]


class AdapterError(Exception):
    pass


class _Fluent2:
    """Fluent 2 (React, @fluentui/react-components v9)."""

    HEADING_TAGS: ClassVar[dict[int, str]] = {1: "h1", 2: "h2", 3: "h3", 4: "h4"}

    def __init__(self, contract: DesignSystemContract) -> None:
        self.contract = contract

    def _c(self, construct: str, index: int = 0) -> str:
        mapping = self.contract.mapping(construct)
        if mapping is None:
            raise AdapterError(f"{self.contract.id} has no mapping for {construct}")
        return mapping.components[index]

    def screen(self, screen: Screen) -> RenderedScreen:
        return RenderedScreen(
            screen_id=screen.id,
            title=screen.title,
            route=screen.route,
            root=[self.node(n) for n in screen.body],
        )

    def node(self, node: Node) -> RenderNode:
        if isinstance(node, Heading):
            return RenderNode(
                component=self._c(f"heading:{node.level}"),
                props={"as": self.HEADING_TAGS[node.level]},
                text=node.text,
                ir_id=node.id,
            )
        if isinstance(node, Text):
            return RenderNode(component=self._c(f"text:{node.tone}"), props={"as": "p"}, text=node.text, ir_id=node.id)
        if isinstance(node, Section):
            props: dict[str, Prop] = {"aria-label": node.title} if node.title else {}
            return RenderNode(
                component=self._c("section"), props=props, children=[self.node(c) for c in node.children], ir_id=node.id
            )
        if isinstance(node, Form):
            return self.form(node)
        if isinstance(node, Table):
            return self.table(node)
        if isinstance(node, Stat):
            return RenderNode(
                component=self._c("stat", 0),
                props={"aria-label": node.label},
                children=[
                    RenderNode(component=self._c("stat", 1), props={"as": "p"}, text=node.label),
                    RenderNode(component=self._c("stat", 2), props={"as": "p"}, text=node.value_hint),
                ],
                ir_id=node.id,
            )
        if isinstance(node, Message):
            body = [RenderNode(component=self._c("message", 2), text=node.title)]
            if node.text:
                body.append(RenderNode(component="span", text=" " + node.text))
            return RenderNode(
                component=self._c("message", 0),
                props={"intent": node.intent},
                children=[RenderNode(component=self._c("message", 1), children=body)],
                ir_id=node.id,
            )
        if isinstance(node, Toolbar):
            return RenderNode(
                component=self._c("toolbar", 0),
                props={"aria-label": node.label},
                children=[
                    RenderNode(
                        component=self._c("toolbar", 1),
                        props={"appearance": "primary" if a.intent == "primary" else "subtle"},
                        text=a.label,
                        ir_id=a.id,
                    )
                    for a in node.actions
                ],
                ir_id=node.id,
            )
        if isinstance(node, Placeholder):
            label = f" ({node.label})" if node.label else ""
            return RenderNode(
                component="div",
                props={"data-unsupported": node.requested_kind},
                text=f"Not supported yet: {node.requested_kind}{label}. {node.reason}",
                ir_id=node.id,
            )
        raise AdapterError(f"unhandled IR node {type(node).__name__}")

    def action(self, action: Action, *, in_form: bool) -> RenderNode:
        appearance = "primary" if action.intent == "primary" else "secondary"
        kind = "submit" if in_form and action.action == "submit" else "button"
        return RenderNode(
            component=self._c(f"action:{action.intent}"),
            props={"appearance": appearance, "type": kind},
            text=action.label,
            ir_id=action.id,
        )

    def field(self, field: FormField) -> RenderNode:
        construct = f"field:{field.input}"
        if field.input == "checkbox":
            props: dict[str, Prop] = {"label": field.label, "name": field.name}
            if field.required:
                props["required"] = True
            return RenderNode(component=self._c(construct), props=props, ir_id=field.id)
        wrapper: dict[str, Prop] = {"label": field.label}
        if field.required:
            wrapper["required"] = True
        if field.help_text:
            wrapper["hint"] = field.help_text
        control = self._c(construct, 1)
        control_props: dict[str, Prop] = {"name": field.name}
        children: list[RenderNode] = []
        if field.input in ("text", "number", "date", "datetime"):
            control_props["type"] = {"text": "text", "number": "number", "date": "date", "datetime": "datetime-local"}[
                field.input
            ]
        elif field.input == "file":
            control_props["type"] = "file"
        elif field.input == "select":
            option = self._c(construct, 2)
            if field.options_from_entity:
                children.append(
                    RenderNode(
                        component=option,
                        props={"value": "", "disabled": True},
                        text=f"Loaded from {field.options_from_entity} at runtime",
                    )
                )
            children.extend(RenderNode(component=option, props={"value": o}, text=o) for o in field.options)
        return RenderNode(
            component=self._c(construct, 0),
            props=wrapper,
            children=[RenderNode(component=control, props=control_props, children=children)],
            ir_id=field.id,
        )

    def form(self, form: Form) -> RenderNode:
        children = [self.field(f) for f in form.fields]
        if form.actions:
            children.append(
                RenderNode(
                    component="div",
                    props={"data-role": "actions"},
                    children=[self.action(a, in_form=True) for a in form.actions],
                )
            )
        return RenderNode(component=self._c("form"), props={"aria-label": form.label}, children=children, ir_id=form.id)

    def table(self, table: Table) -> RenderNode:
        table_c, header_c, row_c, header_cell_c, body_c, cell_c = self.contract.mappings["table"].components[:6]
        headers = [RenderNode(component=header_cell_c, text=c.label) for c in table.columns]
        if table.row_actions:
            headers.append(RenderNode(component=header_cell_c, text="Actions"))
        span = max(1, len(headers))
        return RenderNode(
            component=table_c,
            props={"aria-label": table.caption},
            children=[
                RenderNode(component=header_c, children=[RenderNode(component=row_c, children=headers)]),
                RenderNode(
                    component=body_c,
                    children=[
                        RenderNode(
                            component=row_c,
                            children=[RenderNode(component=cell_c, props={"colSpan": span}, text=table.empty_text)],
                        )
                    ],
                ),
            ],
            ir_id=table.id,
        )


_ADAPTERS: dict[str, Callable[[DesignSystemContract], _Fluent2]] = {"fluent2": _Fluent2}


def has_adapter(contract_id: str) -> bool:
    return contract_id in _ADAPTERS


def render_screens(screens: list[Screen], contract: DesignSystemContract) -> list[RenderedScreen]:
    factory = _ADAPTERS.get(contract.id)
    if factory is None:
        raise AdapterError(f"No adapter for design system '{contract.id}' yet.")
    adapter = factory(contract)
    return [adapter.screen(s) for s in screens]


def components_used(nodes: list[RenderNode]) -> set[str]:
    out: set[str] = set()
    for n in nodes:
        out.add(n.component)
        out |= components_used(n.children)
    return out
