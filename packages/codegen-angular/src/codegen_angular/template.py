"""A tiny, allowlisting builder for Angular templates (ADR-0017).

Templates never contain text from the specification. Spec text lives in a component's ``TEXT``
object as JSON-escaped TypeScript string literals and reaches the page through interpolation
(``{{ t.k3 }}``), which Angular HTML-escapes. Element names and attribute names must be on the
allowlists below; attribute values are either fixed constants or binding expressions built
by the generator from generated identifiers and numbers. Expressions are checked against a
strict character set: no quotes, braces, backticks or angle brackets. Anything else is a
generation error, not output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codegen_react import GenerationError

ELEMENTS = frozenset(
    {
        "h1", "h2", "h3", "h4", "p", "section", "form", "div", "strong", "span", "label",
        "input", "textarea", "select", "option", "button", "table", "th", "td", "tr", "ng-container",
        "mat-form-field", "mat-label", "mat-hint", "mat-error", "mat-checkbox",
    }
)  # fmt: skip

#: Attribute name -> allowed constant values (None: the value must be a checked binding expression;
#: an empty tuple: a boolean attribute that takes no value).
ATTRIBUTES: dict[str, tuple[str, ...] | None] = {
    "class": (
        "subtle", "stat", "stat-label", "stat-value", "toolbar", "actions", "unsupported", "danger",
        "message message-info", "message message-warning", "message message-error", "message message-success",
        "file-field", "mat-mdc-row", "mat-mdc-cell empty", "summary",
    ),
    "role": ("status", "alert", "group", "toolbar"),
    "type": ("text", "number", "date", "datetime-local", "file", "submit", "button"),
    "appearance": ("outline",),
    "step": ("any",),
    "value": ("",),
    "required": (),
    "matInput": (),
    "matNativeControl": (),
    "mat-flat-button": (),
    "mat-stroked-button": (),
    "mat-table": (),
    "mat-header-cell": (),
    "mat-cell": (),
    "mat-header-row": (),
    "mat-row": (),
    "formControlName": None,
    "matColumnDef": None,
    "[attr.aria-label]": None,
    "[attr.colspan]": None,
    "[formGroup]": None,
    "[dataSource]": None,
    "[value]": None,
    "(ngSubmit)": None,
    "(click)": None,
    "(change)": None,
    "*matHeaderCellDef": (),
    "*matCellDef": None,
    "*matHeaderRowDef": None,
    "*matRowDef": None,
    "*matNoDataRow": (),
}  # fmt: skip

_EXPRESSION = re.compile(r"^[A-Za-z0-9_.,;:()$ \[\]-]{1,200}$")
_IDENTIFIER = re.compile(r"^[a-z][A-Za-z0-9]{0,40}$")


def identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise GenerationError(f"unsafe generated identifier {value!r}")
    return value


@dataclass
class Element:
    tag: str
    attrs: list[tuple[str, str | None]] = field(default_factory=list)
    children: list[Element | str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tag not in ELEMENTS:
            raise GenerationError(f"element '{self.tag}' is not allowed in generated templates")
        for name, value in self.attrs:
            if name not in ATTRIBUTES:
                raise GenerationError(f"attribute '{name}' is not allowed on generated elements")
            allowed = ATTRIBUTES[name]
            if allowed is None:
                if value is None or not _EXPRESSION.fullmatch(value):
                    raise GenerationError(f"unsafe expression for {name}: {value!r}")
            elif allowed == ():
                if value is not None:
                    raise GenerationError(f"attribute '{name}' takes no value")
            elif value not in allowed:
                raise GenerationError(f"value {value!r} is not allowed for '{name}'")
        for child in self.children:
            if isinstance(child, str):
                _check_text(child)


def _check_text(text: str) -> None:
    """String children must be interpolations or control-flow lines made by this module."""
    if text.startswith("{{ ") and text.endswith(" }}"):
        interpolate(text[3:-3])
    else:
        control_flow(text)


def interpolate(expression: str) -> str:
    """``{{ expression }}``: the only way text reaches a template."""
    if not _EXPRESSION.fullmatch(expression):
        raise GenerationError(f"unsafe interpolation {expression!r}")
    return "{{ " + expression + " }}"


def control_flow(text: str) -> str:
    """An ``@if``/``@for`` line or a closing brace, built from checked parts."""
    if text == "}" or re.fullmatch(r"@(if|for) \([A-Za-z0-9_.,;:()$ \[\]=>!-]{1,200}\) \{", text):
        return text
    raise GenerationError(f"unsafe control-flow block {text!r}")


VOID = frozenset({"input"})


def render(nodes: list[Element | str], indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    for node in nodes:
        if isinstance(node, str):
            lines.append(pad + node)
            continue
        attrs = "".join(f" {n}" if v is None else f' {n}="{v}"' for n, v in node.attrs)
        if node.tag in VOID:
            lines.append(f"{pad}<{node.tag}{attrs} />")
        elif not node.children:
            lines.append(f"{pad}<{node.tag}{attrs}></{node.tag}>")
        elif all(isinstance(c, str) for c in node.children) and len(node.children) == 1:
            lines.append(f"{pad}<{node.tag}{attrs}>{node.children[0]}</{node.tag}>")
        else:
            lines.append(f"{pad}<{node.tag}{attrs}>")
            lines.extend(render(node.children, indent + 1))
            lines.append(f"{pad}</{node.tag}>")
    return lines


def tags_and_attributes(nodes: list[Element | str]) -> tuple[set[str], set[str]]:
    tags: set[str] = set()
    attrs: set[str] = set()
    for node in nodes:
        if isinstance(node, Element):
            tags.add(node.tag)
            attrs |= {n for n, _ in node.attrs}
            child_tags, child_attrs = tags_and_attributes(node.children)
            tags |= child_tags
            attrs |= child_attrs
    return tags, attrs
