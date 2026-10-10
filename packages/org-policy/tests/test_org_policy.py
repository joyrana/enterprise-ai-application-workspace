from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from appspec import load_spec
from design_system import derive_document
from org_policy import PolicySet, blocking, evaluate

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "packages" / "application-spec" / "examples" / "finance-operations.json"


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def run(raw: dict[str, Any], rules: list[dict[str, Any]], design_system: str = "fluent2") -> list[Any]:
    spec = load_spec(raw)
    policy = PolicySet.model_validate({"rules": rules})
    return evaluate(policy, spec, derive_document(spec), design_system)


def test_empty_policy_finds_nothing(raw: dict[str, Any]) -> None:
    assert run(raw, []) == []


def test_frameworks_and_design_systems(raw: dict[str, Any]) -> None:
    findings = run(
        raw,
        [
            {"id": "angular-only", "kind": "allowed-frameworks", "frameworks": ["angular"]},
            {"id": "brand", "kind": "allowed-design-systems", "ids": ["org-acme"], "severity": "warning"},
        ],
    )
    assert [(f.rule_id, f.severity, f.path) for f in findings] == [
        ("angular-only", "error", "/framework/framework"),
        ("brand", "warning", "/design_system/id"),
    ]
    assert "react is not an allowed framework" in findings[0].message
    assert [f.rule_id for f in blocking(findings)] == ["angular-only"]


def test_forbidden_components_and_form_size(raw: dict[str, Any]) -> None:
    raw["screens"], raw["navigation"] = [], []
    findings = run(
        raw,
        [
            {"id": "no-tables", "kind": "forbidden-components", "constructs": ["table"]},
            {"id": "no-danger", "kind": "forbidden-components", "constructs": ["action:danger"]},
            {"id": "small-forms", "kind": "max-form-fields", "max": 2},
        ],
    )
    by_rule: dict[str, list[str]] = {}
    for f in findings:
        by_rule.setdefault(f.rule_id, []).append(f.path)
    assert len(by_rule["no-tables"]) == 2  # one list screen per entity
    assert all(p.endswith("/row_actions/1") for p in by_rule["no-danger"])  # derived Delete actions
    assert by_rule["small-forms"] == ["/screens/1/body/1"]  # the adjustment form has 3 fields


def test_requirements_rules(raw: dict[str, Any]) -> None:
    raw["acceptance_criteria"] = []
    findings = run(
        raw,
        [
            {"id": "criteria", "kind": "acceptance-criteria-required"},
            {"id": "confirmed", "kind": "confirmed-requirements-only", "severity": "warning"},
        ],
    )
    titles = [r["title"] for r in raw["functional_requirements"]]
    assert [f.rule_id for f in findings if f.rule_id == "criteria"] == ["criteria"] * len(titles)
    unconfirmed = [r for r in raw["functional_requirements"] if r.get("status") != "confirmed"]
    assert len([f for f in findings if f.rule_id == "confirmed"]) == len(unconfirmed)


def test_sensitive_fields_need_a_classification(raw: dict[str, Any]) -> None:
    raw["entities"][1]["fields"].append({"name": "customer-email", "type": "string"})
    rules = [{"id": "pii", "kind": "sensitive-fields", "name_patterns": ["email", "ssn"], "minimum": "confidential"}]
    raw.setdefault("security", {})["classification"] = {
        "value": "internal",
        "status": "proposed",
        "provenance": {"source": "user", "actor": "alice"},
    }
    findings = run(raw, rules)
    assert [f.path for f in findings] == ["/entities/1/fields/1"]
    assert "at least 'confidential' (it is internal)" in findings[0].message
    raw["security"]["classification"]["value"] = "restricted"
    assert run(raw, rules) == []


def test_entity_naming_and_screen_states(raw: dict[str, Any]) -> None:
    findings = run(
        raw,
        [
            {"id": "naming", "kind": "entity-naming", "pattern": "fin-[a-z-]+"},
            {"id": "states", "kind": "required-screen-states", "states": ["empty", "error"]},
        ],
    )
    assert [f.rule_id for f in findings] == ["naming", "naming"]
    raw["screens"][0]["states"] = ["loading"]
    findings = run(raw, [{"id": "states", "kind": "required-screen-states", "states": ["empty", "error"]}])
    assert findings[0].message == "Screen 'Adjustment rules' does not define: empty, error."


def test_policy_documents_are_validated() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PolicySet.model_validate({"rules": [{"id": "a1", "kind": "max-form-fields", "max": 3}] * 2})
    with pytest.raises(ValidationError, match="regular expression"):
        PolicySet.model_validate({"rules": [{"id": "n1", "kind": "entity-naming", "pattern": "("}]})
    with pytest.raises(ValidationError):
        PolicySet.model_validate({"rules": [{"id": "x1", "kind": "run-this-script", "code": "rm -rf /"}]})
    with pytest.raises(ValidationError):
        PolicySet.model_validate({"rules": [{"id": "Bad Id", "kind": "acceptance-criteria-required"}]})
