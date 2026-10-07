"""Print a render tree as TSX. Data never becomes code.

* Every string from the spec is emitted as a JSON string literal inside braces
  (``{"..."}``) with ``ensure_ascii``: quotes, backslashes, braces, ``*/``,
  line separators and non-ASCII characters cannot end the literal.
* Component names and prop names must be on an allowlist (the same one the
  workspace preview uses); anything else is a :class:`GenerationError`, not
  output.
* Prop values are type-checked (string, int, bool) and enumerated values are
  checked against their allowed sets.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from design_system import RenderNode
from design_system.ir import Form as IrForm
from design_system.ir import FormField as IrField
from design_system.ir import Table as IrTable


class GenerationError(Exception):
    pass


def literal(value: str) -> str:
    """A TypeScript string literal for arbitrary text."""
    return json.dumps(value, ensure_ascii=True)


Check = Callable[[object], bool]


def _str(v: object) -> bool:
    return isinstance(v, str) and len(v) <= 2000


def _bool(v: object) -> bool:
    return isinstance(v, bool)


def _small_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 < v < 100


def _length(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100_000


def _route(v: object) -> bool:
    return isinstance(v, str) and re.fullmatch(r"/[a-z0-9/-]{0,199}", v) is not None


def _short(v: object) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 200


def _one_of(*values: str) -> Check:
    return lambda v: isinstance(v, str) and v in values


_TYPO: dict[str, Check] = {"as": _one_of("h1", "h2", "h3", "h4", "p", "span")}

#: component -> allowed props. Mirrors apps/workspace-web/src/design/RenderTree.tsx (tested for equality).
ALLOWED: dict[str, dict[str, Check]] = {
    "Title1": _TYPO,
    "Title2": _TYPO,
    "Title3": _TYPO,
    "Subtitle1": _TYPO,
    "Subtitle2": _TYPO,
    "Body1": _TYPO,
    "Body1Strong": _TYPO,
    "Caption1": _TYPO,
    "Field": {"label": _str, "required": _bool, "hint": _str},
    "Input": {
        "name": _str,
        "type": _one_of("text", "number", "date", "datetime-local"),
        "required": _bool,
        "min": _short,
        "max": _short,
        "minLength": _length,
        "maxLength": _length,
        "pattern": _short,
        "step": _one_of("any"),
    },
    "Textarea": {"name": _str, "required": _bool, "minLength": _length, "maxLength": _length},
    "Select": {"name": _str, "required": _bool},
    "Checkbox": {"label": _str, "name": _str, "required": _bool},
    "Button": {
        "appearance": _one_of("primary", "secondary"),
        "type": _one_of("button", "submit"),
        "navigateTo": _route,
    },
    "Table": {"aria-label": _str},
    "TableHeader": {},
    "TableRow": {},
    "TableHeaderCell": {},
    "TableBody": {},
    "TableCell": {"colSpan": _small_int},
    "Card": {"aria-label": _str},
    "MessageBar": {"intent": _one_of("info", "warning", "error", "success")},
    "MessageBarBody": {},
    "MessageBarTitle": {},
    "Toolbar": {"aria-label": _str},
    "ToolbarButton": {"appearance": _one_of("primary", "subtle"), "navigateTo": _route},
    "form": {"aria-label": _str},
    "section": {"aria-label": _str},
    "div": {"data-unsupported": _str, "data-role": _one_of("actions")},
    "span": {},
    "option": {"value": _str, "disabled": _bool},
    "input": {"type": _one_of("file"), "name": _str},
}

_PROP_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*$")


def is_library_component(name: str) -> bool:
    return name[:1].isupper()


#: Props that become behaviour in generated code rather than attributes.
_BEHAVIOUR_PROPS = {"navigateTo"}


def _props(node: RenderNode) -> str:
    allowed = ALLOWED.get(node.component)
    if allowed is None:
        raise GenerationError(f"component '{node.component}' is not allowed")
    parts: list[str] = []
    for key in sorted(node.props):
        value = node.props[key]
        check = allowed.get(key)
        if check is None or not _PROP_NAME.fullmatch(key):
            raise GenerationError(f"prop '{key}' is not allowed on {node.component}")
        if not check(value):
            raise GenerationError(f"invalid value for {node.component}.{key}")
        if key in _BEHAVIOUR_PROPS:
            continue
        if isinstance(value, bool):
            parts.append(key if value else f"{key}={{false}}")
        elif isinstance(value, int):
            parts.append(f"{key}={{{value}}}")
        else:
            parts.append(f"{key}={{{literal(value)}}}")
    return "".join(f" {p}" for p in parts)


def _classes(node: RenderNode) -> str:
    if node.component == "form":
        return " className={layout.form}"
    if node.component == "div" and node.props.get("data-role") == "actions":
        return " className={layout.actions}"
    if node.component == "div" and "data-unsupported" in node.props:
        return " className={layout.unsupported}"
    if node.component == "section":
        return " className={layout.section}"
    return ""


def _control_name(field: RenderNode) -> str | None:
    for child in field.children:
        name = child.props.get("name")
        if isinstance(name, str):
            return name
    return None


@dataclass
class DataBindings:
    """What the printer needs to bind tables, forms and reference fields to entity stores."""

    #: IR node id -> IR node (tables, forms, fields), to find entity bindings for render nodes.
    ir_nodes: dict[str, object] = field(default_factory=dict)
    #: Entities that have a generated store.
    entities: set[str] = field(default_factory=set)
    #: (entity id, field name) -> referenced entity id.
    references: dict[tuple[str, str], str] = field(default_factory=dict)
    #: entity id -> route of its list screen, where a bound form returns after saving.
    list_routes: dict[str, str] = field(default_factory=dict)
    #: Route of the screen being printed (a form never "returns" to its own screen).
    current_route: str = ""


class Printer:
    """Prints one screen's render tree; records which hooks and components the output needs."""

    def __init__(self, bindings: DataBindings | None = None) -> None:
        self.bindings = bindings or DataBindings()
        self.form_args: dict[str, str] = {}
        self.bound_forms: set[str] = set()
        self.data_hooks: list[str] = []
        self.data_imports: set[str] = set()
        self.store_imports: set[str] = set()
        self.forms: list[str] = []
        #: form variable -> field name -> label, for the error summary.
        self.labels: dict[str, dict[str, str]] = {}
        self.uses_navigate = False
        self.extra_components: set[str] = set()

    def _behaviour(self, node: RenderNode, form_var: str | None) -> str:
        out = ""
        target = node.props.get("navigateTo")
        if isinstance(target, str):
            self.uses_navigate = True
            out += f" onClick={{() => navigate({literal(target)})}}"
        if node.component == "form":
            var = f"form{len(self.forms) + 1}"
            self.forms.append(var)
            out += f" noValidate onSubmit={{{var}.onSubmit}}"
            self._bind_form(node, var)
        if node.component == "Checkbox" and form_var is not None:
            name, label = node.props.get("name"), node.props.get("label")
            if isinstance(name, str) and isinstance(label, str):
                self.labels.setdefault(form_var, {})[name] = label
        if node.component == "Field" and form_var is not None:
            name = _control_name(node)
            label = node.props.get("label")
            if name is not None and isinstance(label, str):
                self.labels.setdefault(form_var, {})[name] = label
            if name is not None:
                key = f"{form_var}.errors[{literal(name)}]"
                out += f' validationMessage={{{key}}} validationState={{{key} ? "error" : "none"}}'
        return out

    def _ir(self, node: RenderNode) -> object | None:
        return self.bindings.ir_nodes.get(node.ir_id) if node.ir_id else None

    def _bind_form(self, node: RenderNode, var: str) -> None:
        ir = self._ir(node)
        if not isinstance(ir, IrForm) or ir.entity_id not in self.bindings.entities:
            return
        entity = literal(ir.entity_id)
        self.bound_forms.add(var)
        self.data_imports.add("saveRecord")
        route = self.bindings.list_routes.get(ir.entity_id)
        if route and route != self.bindings.current_route:
            self.uses_navigate = True
            self.form_args[var] = f"{{ save: (data) => {{ saveRecord({entity}, data); navigate({literal(route)}); }} }}"
        else:
            self.form_args[var] = f"{{ save: (data) => saveRecord({entity}, data) }}"

    def _hook(self, kind: str, entity: str) -> str:
        var = f"{kind}{len(self.data_hooks) + 1}"
        self.data_hooks.append(f"const {var} = useEntityList(stores[{literal(entity)}]);")
        self.store_imports.add("useEntityList")
        self.data_imports.add("stores")
        return var

    def _bound_table(self, node: RenderNode, ir: IrTable, pad: str, attrs: str, depth: int) -> list[str]:
        assert ir.entity_id is not None
        header, body = node.children[0], node.children[1]
        row_c = body.children[0].component
        empty_cell = body.children[0].children[0]
        cell_c = empty_cell.component
        rows = self._hook("rows", ir.entity_id)
        self.data_imports.add("formatValue")
        cells = []
        for column in ir.columns:
            key = literal(column.key)
            ref = self.bindings.references.get((ir.entity_id, column.key))
            if column.type == "reference" and ref in self.bindings.entities:
                self.data_imports.add("displayRef")
                cells.append(f"<{cell_c}>{{displayRef({literal(ref)}, row[{key}])}}</{cell_c}>")
            else:
                cells.append(f"<{cell_c}>{{formatValue(row[{key}])}}</{cell_c}>")
        lines = [f"{pad}<{node.component}{attrs}>"]
        lines.extend(self.nodes([header], len(pad) // 2 + 1, depth + 1))
        p = pad + "  "
        lines += [
            f"{p}<{body.component}>",
            f"{p}  {{{rows}.length === 0 ? (",
            f"{p}    <{row_c}>",
            *[f"{p}      {line.strip()}" for line in self.nodes([empty_cell], 0, depth + 1)],
            f"{p}    </{row_c}>",
            f"{p}  ) : (",
            f"{p}    {rows}.map((row) => (",
            f"{p}      <{row_c} key={{row.id}}>",
            *[f"{p}        {c}" for c in cells],
            f"{p}      </{row_c}>",
            f"{p}    ))",
            f"{p}  )}}",
            f"{p}</{body.component}>",
            f"{pad}</{node.component}>",
        ]
        return lines

    def _reference_field(self, node: RenderNode, ref: str, pad: str, attrs: str) -> list[str]:
        select = node.children[0]
        option_c = "option"
        options = self._hook("options", ref)
        self.data_imports.add("displayName")
        return [
            f"{pad}<{node.component}{attrs}>",
            f"{pad}  <{select.component}{_props(select)}>",
            f'{pad}    <{option_c} value="">{{{literal("Select…")}}}</{option_c}>',
            f"{pad}    {{{options}.map((record) => (",
            f"{pad}      <{option_c} key={{record.id}} value={{record.id}}>",
            f"{pad}        {{displayName({literal(ref)}, record)}}",
            f"{pad}      </{option_c}>",
            f"{pad}    ))}}",
            f"{pad}  </{select.component}>",
            f"{pad}</{node.component}>",
        ]

    def declarations(self) -> list[str]:
        out = ["const navigate = useNavigate();"] if self.uses_navigate else []
        out += self.data_hooks
        out += [f"const {var} = useFormState({self.form_args.get(var, '')});" for var in self.forms]
        return out

    def _form_feedback(self, var: str, pad: str) -> list[str]:
        self.extra_components |= {"MessageBar", "MessageBarBody", "MessageBarTitle"}
        return [
            f"{pad}{{Object.keys({var}.errors).length > 0 && (",
            f'{pad}  <MessageBar intent="error">',
            f"{pad}    <MessageBarBody>",
            f"{pad}      <MessageBarTitle>{{`Fix ${{Object.keys({var}.errors).length}} field(s)`}}</MessageBarTitle>",
            f"{pad}      {{Object.keys({var}.errors)",
            f"{pad}        .map((name) => {var.upper()}_LABELS[name] ?? name)",
            f'{pad}        .join(", ")}}',
            f"{pad}    </MessageBarBody>",
            f"{pad}  </MessageBar>",
            f"{pad})}}",
            f"{pad}{{{var}.submitted && (",
            f'{pad}  <MessageBar intent="success">',
            f"{pad}    <MessageBarBody>",
            *(
                [
                    f"{pad}      <MessageBarTitle>Saved</MessageBarTitle>",
                    f"{pad}      The record was saved in this browser.",
                ]
                if var in self.bound_forms
                else [
                    f"{pad}      <MessageBarTitle>Validated</MessageBarTitle>",
                    f"{pad}      Saving is not connected to a backend yet.",
                ]
            ),
            f"{pad}    </MessageBarBody>",
            f"{pad}  </MessageBar>",
            f"{pad})}}",
        ]

    def label_constants(self) -> list[str]:
        out: list[str] = []
        for var in self.forms:
            entries = ", ".join(f"{literal(k)}: {literal(v)}" for k, v in sorted(self.labels.get(var, {}).items()))
            out.append(f"const {var.upper()}_LABELS: Record<string, string> = {{ {entries} }};")
        return out

    def nodes(self, nodes: list[RenderNode], indent: int, depth: int = 0, form_var: str | None = None) -> list[str]:
        if depth > 24:
            raise GenerationError("render tree is too deep")
        pad = "  " * indent
        lines: list[str] = []
        for node in nodes:
            tag = node.component
            attrs = _props(node) + _classes(node) + self._behaviour(node, form_var)
            inner_form = self.forms[-1] if tag == "form" else form_var
            ir = self._ir(node)
            if (
                tag == "Table"
                and isinstance(ir, IrTable)
                and ir.entity_id in self.bindings.entities
                and len(node.children) == 2
            ):
                lines.extend(self._bound_table(node, ir, pad, attrs, depth))
                continue
            if (
                tag == "Field"
                and isinstance(ir, IrField)
                and ir.options_from_entity in self.bindings.entities
                and len(node.children) == 1
            ):
                lines.extend(self._reference_field(node, str(ir.options_from_entity), pad, attrs))
                continue
            only = node.children[0] if len(node.children) == 1 else None
            if tag == "Field" and only is not None and only.component == "input":
                lines.append(f"{pad}<Field{attrs}>")
                lines.append(f"{pad}  {{(fieldProps) => <input {{...fieldProps}}{_props(only)} />}}")
                lines.append(f"{pad}</Field>")
                continue
            if node.text is None and not node.children and tag != "form":
                lines.append(f"{pad}<{tag}{attrs} />")
                continue
            if node.text is not None and not node.children:
                lines.append(f"{pad}<{tag}{attrs}>{{{literal(node.text)}}}</{tag}>")
                continue
            lines.append(f"{pad}<{tag}{attrs}>")
            if node.text is not None:
                lines.append(f"{pad}  {{{literal(node.text)}}}")
            lines.extend(self.nodes(node.children, indent + 1, depth + 1, inner_form))
            if tag == "form" and inner_form is not None:
                lines.extend(self._form_feedback(inner_form, pad + "  "))
            lines.append(f"{pad}</{tag}>")
        return lines


def print_nodes(nodes: list[RenderNode], indent: int, depth: int = 0) -> list[str]:
    return Printer().nodes(nodes, indent, depth)


def components_in(nodes: list[RenderNode]) -> set[str]:
    out: set[str] = set()
    for n in nodes:
        out.add(n.component)
        out |= components_in(n.children)
    return out


def needs_layout(nodes: list[RenderNode]) -> bool:
    """Whether printing these nodes references the shared layout classes."""
    return any(_classes(n) or needs_layout(n.children) for n in nodes)
