from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from appspec import ApplicationSpec, load_spec
from design_system import (
    IR_CONSTRUCTS,
    UiDocument,
    builtin_contracts,
    components_used,
    derive_document,
    get_contract,
    humanize,
    json_schema,
    missing_constructs,
    render_screens,
    validate_document,
)
from design_system.ir import Action, Form, FormField, Heading, Placeholder, Screen, ScreenSource, Table, Text

EXAMPLE = Path(__file__).resolve().parents[2] / "application-spec" / "examples" / "finance-operations.json"
HTML_ALLOWED = {"div", "span"}


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def spec(raw: dict[str, Any]) -> ApplicationSpec:
    return load_spec(raw)


def screen(*body: Any, sid: str = "s", route: str = "/s") -> Screen:
    return Screen(id=sid, title="S", route=route, source=ScreenSource(kind="spec-screen", ref=sid), body=list(body))


def codes(doc: UiDocument, spec: ApplicationSpec | None = None) -> list[str]:
    return [i.code for i in validate_document(doc, spec)]


# --------------------------------------------------------------------------- derivation


def test_spec_screens_become_ir_screens(spec: ApplicationSpec) -> None:
    doc = derive_document(spec, spec_revision=3)
    assert doc.spec_revision == 3
    [s] = doc.screens
    assert (s.id, s.route, s.source.kind) == ("adjustment-rules", "/adjustment-rules", "spec-screen")
    assert s.requirement_ids == ["configure-adjustments"]
    heading, table = s.body
    assert isinstance(heading, Heading)
    assert heading.level == 1
    assert isinstance(table, Table)
    assert [c.key for c in table.columns] == ["amount", "kind", "transaction"]
    assert [c.type for c in table.columns] == ["money", "text", "reference"]
    assert validate_document(doc, spec) == []


def test_entities_give_list_and_form_screens_when_no_screens_exist(raw: dict[str, Any]) -> None:
    raw["screens"] = []
    raw["navigation"] = []
    spec = load_spec(raw)
    doc = derive_document(spec)
    assert [s.id for s in doc.screens] == ["adjustment-list", "adjustment-form", "transaction-list", "transaction-form"]
    form = next(n for n in doc.screens[1].body if isinstance(n, Form))
    inputs = {f.name: f for f in form.fields}
    assert inputs["amount"].input == "number"
    assert inputs["amount"].required is True
    assert inputs["kind"].input == "select"
    assert inputs["kind"].options == ["accrual", "reclass", "write-off"]
    assert inputs["transaction"].options_from_entity == "transaction"
    assert [a.intent for a in form.actions] == ["primary", "secondary"]
    assert form.actions[1].target_screen == "adjustment-list"
    assert validate_document(doc, spec) == []


def test_unexpressible_components_become_placeholders_not_guesses(raw: dict[str, Any]) -> None:
    raw["screens"][0]["components"] = [
        {"id": "trend", "kind": "chart", "label": "Adjustments over time"},
        {"id": "orphan", "kind": "table", "entity_id": "missing"},
        {"id": "total", "kind": "metric", "label": "Open adjustments"},
    ]
    spec = load_spec(raw)
    doc = derive_document(spec)
    kinds = [n.kind for n in doc.screens[0].body]
    assert kinds == ["heading", "placeholder", "placeholder", "stat"]
    chart = doc.screens[0].body[1]
    assert isinstance(chart, Placeholder)
    assert chart.reason == "charts are not part of IR v1"
    issues = validate_document(doc, spec)
    assert [(i.code, i.severity) for i in issues] == [("unsupported-component", "warning")] * 2


def test_derivation_is_deterministic(spec: ApplicationSpec) -> None:
    assert derive_document(spec).model_dump() == derive_document(spec).model_dump()


def test_humanize() -> None:
    assert humanize("risk-score") == "Risk score"
    assert humanize("amount") == "Amount"


# --------------------------------------------------------------------------- validation


def test_accessibility_rules() -> None:
    doc = UiDocument(
        screens=[
            screen(
                Heading(id="a", text="A", level=1),
                Heading(id="b", text="B", level=3),
                Heading(id="c", text="C", level=1),
                Form(
                    id="f",
                    label="F",
                    fields=[FormField(id="f1", name="x", label="X", input="select")],
                    actions=[
                        Action(id="a1", label="Save", intent="primary", action="submit"),
                        Action(id="a2", label="Also", intent="primary"),
                    ],
                ),
                Table(id="t", caption="T"),
            )
        ]
    )
    assert sorted(codes(doc)) == sorted(
        ["a11y-one-h1", "a11y-heading-order", "select-no-options", "form-one-primary", "table-no-columns"]
    )


def test_references_and_duplicates(spec: ApplicationSpec) -> None:
    doc = UiDocument(
        screens=[
            screen(
                Heading(id="h", text="H", level=1),
                Table(id="t", caption="T", entity_id="nope", columns=[]),
                Text(id="h", text="dup"),
            ),
            screen(
                Heading(id="h2", text="H", level=1),
                Form(
                    id="f",
                    label="F",
                    fields=[FormField(id="x", name="x", label="X", input="text")],
                    actions=[Action(id="go", label="Go", action="navigate", target_screen="nowhere")],
                ),
                sid="s2",
                route="/s",
            ),
        ]
    )
    found = codes(doc, spec)
    for code in ("ref-entity", "id-duplicate", "route-duplicate", "ref-screen", "form-no-submit"):
        assert code in found


def test_entity_lists_get_edit_and_delete_row_actions(raw: dict[str, Any]) -> None:
    raw["screens"], raw["navigation"] = [], []
    doc = derive_document(load_spec(raw))
    table = next(n for n in doc.screens[0].body if isinstance(n, Table))
    assert [(a.action, a.target_screen, a.intent) for a in table.row_actions] == [
        ("edit-record", "adjustment-form", "secondary"),
        ("delete-record", None, "danger"),
    ]
    edit_nowhere = Action(id="e", label="Edit", action="edit-record", target_screen="nowhere")
    broken = UiDocument(
        screens=[screen(Heading(id="h", text="H", level=1), Table(id="t", caption="T", row_actions=[edit_nowhere]))]
    )
    assert "ref-screen" in codes(broken)


def test_ir_rejects_unknown_fields_and_bad_ids() -> None:
    with pytest.raises(ValidationError):
        Heading.model_validate({"id": "Bad Id", "text": "x", "level": 1})
    with pytest.raises(ValidationError):
        Heading.model_validate({"id": "ok", "text": "x", "level": 1, "onClick": "alert(1)"})
    with pytest.raises(ValidationError):
        Heading.model_validate({"id": "ok", "text": "x", "level": 7})


def test_ir_json_schema_is_versioned() -> None:
    schema = json_schema()
    assert schema["$id"] == "urn:workspace:ui-ir:1"


# --------------------------------------------------------------------------- contracts and adapter


def test_fluent2_contract_is_complete_and_pinned() -> None:
    contract = get_contract("fluent2")
    assert contract is not None
    assert missing_constructs(contract) == []
    assert contract.framework == "react"
    assert contract.library.package == "@fluentui/react-components"
    assert contract.library.version == "9.74.9"
    assert set(builtin_contracts()) == {"fluent2", "material3"}
    assert set(contract.mappings) <= set(IR_CONSTRUCTS)


def test_material3_contract_is_complete_and_pinned_for_angular() -> None:
    contract = get_contract("material3")
    assert contract is not None
    assert missing_constructs(contract) == []
    assert contract.framework == "angular"
    assert (contract.library.package, contract.library.version) == ("@angular/material", "22.2.2")
    assert set(contract.mappings) == set(IR_CONSTRUCTS)
    assert contract.mappings["field:select"].components[2] == "select[matNativeControl]"
    assert all(token.startswith("--mat-sys-") for token in contract.tokens.values())


def test_rendered_components_all_come_from_the_contract(raw: dict[str, Any]) -> None:
    contract = get_contract("fluent2")
    assert contract is not None
    raw["screens"] = []
    raw["navigation"] = []
    doc = derive_document(load_spec(raw))
    rendered = render_screens(doc.screens, contract)
    allowed = {c for m in contract.mappings.values() for c in m.components} | HTML_ALLOWED
    used = components_used([n for s in rendered for n in s.root])
    assert used <= allowed
    assert {"Field", "Select", "Button", "Table", "Toolbar"} <= used


def test_fluent2_rendering_keeps_labels_and_semantics(spec: ApplicationSpec) -> None:
    contract = get_contract("fluent2")
    assert contract is not None
    form = Form(
        id="f",
        label="New adjustment",
        fields=[
            FormField(
                id="f-amount",
                name="amount",
                label="Amount",
                input="number",
                required=True,
                help_text="EUR",
                number_kind="decimal",
            ),
            FormField(id="f-ok", name="ok", label="Approved", input="checkbox"),
            FormField(id="f-kind", name="kind", label="Kind", input="select", options=["a", "b"]),
        ],
        actions=[Action(id="f-save", label="Save", intent="primary", action="submit")],
    )
    [rendered] = render_screens([screen(Heading(id="h", text="New", level=1), form)], contract)
    title, form_node = rendered.root
    assert (title.component, title.props, title.text) == ("Title2", {"as": "h1"}, "New")
    amount, approved, kind, actions = form_node.children
    assert amount.component == "Field"
    assert amount.props == {"label": "Amount", "required": True, "hint": "EUR"}
    assert amount.children[0].props == {"name": "amount", "type": "number", "required": True, "step": "any"}
    assert approved.component == "Checkbox"
    assert approved.props == {"label": "Approved", "name": "ok"}
    assert [o.text for o in kind.children[0].children] == ["a", "b"]
    assert actions.children[0].props == {"appearance": "primary", "type": "submit"}
    assert form_node.props == {"aria-label": "New adjustment"}


def test_fluent2_contract_pins_the_version_the_workspace_locks() -> None:
    lock = Path(__file__).resolve().parents[3] / "apps" / "workspace-web" / "package-lock.json"
    locked = json.loads(lock.read_text(encoding="utf-8"))["packages"]["node_modules/@fluentui/react-components"]
    contract = get_contract("fluent2")
    assert contract is not None
    assert contract.library.version == locked["version"]


def test_brand_themes_are_validated_for_contrast_and_safe_fonts() -> None:
    from design_system import BrandTheme, BrandThemeSet, brand_ramp, contrast

    assert round(contrast("#000000", "#ffffff"), 1) == 21.0
    theme = BrandTheme(id="acme", name="Acme", base="fluent2", brand_color="#8A1538")
    assert theme.brand_color == "#8a1538"
    assert theme.selector == "org-acme"
    ramp = brand_ramp(theme.brand_color)
    assert list(ramp) == list(range(10, 161, 10))
    assert ramp[80] == "#8a1538"
    assert contrast(ramp[10], "#ffffff") > contrast(ramp[80], "#ffffff") > contrast(ramp[160], "#ffffff")
    with pytest.raises(ValidationError, match="contrast"):
        BrandTheme(id="pale", name="Pale", base="fluent2", brand_color="#9ec5ff")
    with pytest.raises(ValidationError):
        BrandTheme(id="css", name="X", base="fluent2", brand_color="#8a1538", font_family="x; } body { color: red")
    with pytest.raises(ValidationError, match="unique"):
        BrandThemeSet(items=[theme, theme])
    assert BrandThemeSet(items=[theme]).get("org-acme") == theme
