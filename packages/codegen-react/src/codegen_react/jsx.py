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

from design_system import RenderNode


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
    "Input": {"name": _str, "type": _one_of("text", "number", "date", "datetime-local")},
    "Textarea": {"name": _str},
    "Select": {"name": _str},
    "Checkbox": {"label": _str, "name": _str, "required": _bool},
    "Button": {"appearance": _one_of("primary", "secondary"), "type": _one_of("button", "submit")},
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
    "ToolbarButton": {"appearance": _one_of("primary", "subtle")},
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
        if isinstance(value, bool):
            parts.append(key if value else f"{key}={{false}}")
        elif isinstance(value, int):
            parts.append(f"{key}={{{value}}}")
        else:
            parts.append(f"{key}={{{literal(value)}}}")
    return "".join(f" {p}" for p in parts)


def _classes(node: RenderNode) -> str:
    if node.component == "form":
        return " className={layout.form} onSubmit={preventSubmit}"
    if node.component == "div" and node.props.get("data-role") == "actions":
        return " className={layout.actions}"
    if node.component == "div" and "data-unsupported" in node.props:
        return " className={layout.unsupported}"
    if node.component == "section":
        return " className={layout.section}"
    return ""


def print_nodes(nodes: list[RenderNode], indent: int, depth: int = 0) -> list[str]:
    if depth > 24:
        raise GenerationError("render tree is too deep")
    pad = "  " * indent
    lines: list[str] = []
    for node in nodes:
        tag = node.component
        attrs = _props(node) + _classes(node)
        only = node.children[0] if len(node.children) == 1 else None
        if tag == "Field" and only is not None and only.component == "input":
            input_attrs = _props(only)
            lines.append(f"{pad}<Field{attrs}>")
            lines.append(f"{pad}  {{(fieldProps) => <input {{...fieldProps}}{input_attrs} />}}")
            lines.append(f"{pad}</Field>")
            continue
        if node.text is None and not node.children:
            lines.append(f"{pad}<{tag}{attrs} />")
            continue
        if node.text is not None and not node.children:
            lines.append(f"{pad}<{tag}{attrs}>{{{literal(node.text)}}}</{tag}>")
            continue
        lines.append(f"{pad}<{tag}{attrs}>")
        if node.text is not None:
            lines.append(f"{pad}  {{{literal(node.text)}}}")
        lines.extend(print_nodes(node.children, indent + 1, depth + 1))
        lines.append(f"{pad}</{tag}>")
    return lines


def components_in(nodes: list[RenderNode]) -> set[str]:
    out: set[str] = set()
    for n in nodes:
        out.add(n.component)
        out |= components_in(n.children)
    return out


def needs_layout(nodes: list[RenderNode]) -> bool:
    """Whether printing these nodes references the shared layout classes."""
    return any(_classes(n) or needs_layout(n.children) for n in nodes)
