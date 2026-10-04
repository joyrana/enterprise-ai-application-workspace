from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from appspec import (
    SCHEMA_VERSION,
    ApplicationSpec,
    FactStatus,
    UnsupportedSchemaVersion,
    canonical_json,
    content_hash,
    has_errors,
    json_schema,
    json_schema_text,
    load_spec,
    semantic_fingerprint,
    stamp_revisions,
    summarize,
    validate_spec,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "finance-operations.json"
USER = {"source": "user", "actor": "u1"}


@pytest.fixture
def raw() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------------------- structure


def test_example_spec_is_valid_and_has_no_errors(raw: dict[str, Any]) -> None:
    spec = load_spec(raw)
    issues = validate_spec(spec)
    assert not has_errors(issues), issues
    # Two requirements have no acceptance criteria; that is a warning, not an error.
    assert {i.code for i in issues} == {"requirement-without-acceptance-criteria"}
    assert len(issues) == 2


def test_empty_spec_marks_everything_unknown() -> None:
    spec = ApplicationSpec.empty("New project")
    assert spec.schema_version == SCHEMA_VERSION
    assert spec.objective.status is FactStatus.UNKNOWN
    assert spec.objective.value is None
    assert spec.framework.framework.status is FactStatus.UNKNOWN
    assert validate_spec(spec) == []


def test_unknown_fields_are_rejected(raw: dict[str, Any]) -> None:
    raw["metadata"]["nmae"] = "typo"
    with pytest.raises(ValidationError, match="nmae"):
        load_spec(raw)


@pytest.mark.parametrize(
    ("fact", "message"),
    [
        ({"value": "x", "status": "unknown"}, "must not carry a value"),
        ({"status": "proposed", "provenance": USER}, "must carry a value"),
        ({"value": "x", "status": "proposed"}, "must record its provenance"),
        ({"value": "x", "status": "confirmed", "provenance": USER}, "confirmed_by"),
        ({"value": "x", "status": "proposed", "provenance": USER, "confirmed_by": "u1"}, "cannot have confirmed_by"),
    ],
)
def test_fact_status_invariants(fact: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ApplicationSpec.model_validate({"metadata": {"name": "p"}, "objective": fact})


def test_model_provenance_requires_skill_and_model() -> None:
    fact = {"value": "x", "status": "proposed", "provenance": {"source": "model"}}
    with pytest.raises(ValidationError, match="skill_id and model_id"):
        ApplicationSpec.model_validate({"metadata": {"name": "p"}, "objective": fact})


def test_duplicate_ids_across_collections_are_rejected(raw: dict[str, Any]) -> None:
    raw["roles"][0]["id"] = "ops-analyst"  # same as a persona id
    with pytest.raises(ValidationError, match="duplicate id 'ops-analyst'"):
        load_spec(raw)


def test_duplicate_nested_navigation_ids_are_rejected() -> None:
    nav = [{"id": "a", "label": "A", "children": [{"id": "a", "label": "Again"}]}]
    with pytest.raises(ValidationError, match="duplicate navigation id"):
        ApplicationSpec.model_validate({"metadata": {"name": "p"}, "navigation": nav})


@pytest.mark.parametrize("bad_id", ["Upper", "1starts-with-digit", "has space", "x" * 65, ""])
def test_identifier_format(raw: dict[str, Any], bad_id: str) -> None:
    raw["personas"][0]["id"] = bad_id
    with pytest.raises(ValidationError):
        load_spec(raw)


def test_enum_field_requires_values(raw: dict[str, Any]) -> None:
    raw["entities"][0]["fields"][1]["enum_values"] = []
    with pytest.raises(ValidationError, match="must list enum_values"):
        load_spec(raw)


# --------------------------------------------------------------------------- semantics


def test_dangling_references_are_reported_with_paths(raw: dict[str, Any]) -> None:
    raw["acceptance_criteria"][0]["requirement_id"] = "does-not-exist"
    raw["navigation"][0]["screen_id"] = "missing-screen"
    raw["entities"][0]["relationships"][0]["target_entity_id"] = "ghost"
    raw["open_questions"][0]["related_ids"] = ["nowhere"]
    issues = [i for i in validate_spec(load_spec(raw)) if i.code == "dangling-reference"]
    assert sorted(i.path for i in issues) == [
        "/acceptance_criteria/0/requirement_id",
        "/entities/0/relationships/0/target_entity_id",
        "/navigation/0/screen_id",
        "/open_questions/0/related_ids/0",
    ]
    assert has_errors(issues)


# --------------------------------------------------------------------------- versioning


def test_unsupported_schema_version_is_rejected(raw: dict[str, Any]) -> None:
    raw["schema_version"] = "9.9.9"
    with pytest.raises(UnsupportedSchemaVersion):
        load_spec(raw)


def test_missing_schema_version_is_rejected(raw: dict[str, Any]) -> None:
    del raw["schema_version"]
    with pytest.raises(UnsupportedSchemaVersion):
        load_spec(raw)


# --------------------------------------------------------------------------- serialization


def test_canonical_json_round_trips_and_hash_is_stable(raw: dict[str, Any]) -> None:
    spec = load_spec(raw)
    text = canonical_json(spec)
    again = load_spec(json.loads(text))
    assert canonical_json(again) == text
    assert content_hash(again) == content_hash(spec)
    assert content_hash(spec).startswith("sha256:")


def test_hash_ignores_key_order(raw: dict[str, Any]) -> None:
    reordered = json.loads(json.dumps(raw, sort_keys=True))
    assert content_hash(load_spec(reordered)) == content_hash(load_spec(raw))


def test_json_schema_is_exported_and_deterministic() -> None:
    schema = json_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert "metadata" in schema["required"]
    assert json_schema_text() == json_schema_text()


def test_json_schema_validates_example_with_jsonschema(raw: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(json_schema()).validate(raw)


# --------------------------------------------------------------------------- revisions


def test_first_revision_stamps_everything(raw: dict[str, Any]) -> None:
    stamped = stamp_revisions(None, load_spec(raw), 1)
    assert stamped.objective.revision.created_in == 1
    assert stamped.personas[0].revision.updated_in == 1
    assert stamped.accessibility.standard.revision.created_in == 1


def test_revision_stamping_tracks_changes_by_id(raw: dict[str, Any]) -> None:
    v1 = stamp_revisions(None, load_spec(raw), 1)
    raw2 = copy.deepcopy(raw)
    raw2["personas"][1]["name"] = "Senior finance approver"  # changed
    raw2["personas"].reverse()  # reordering alone is not a change
    raw2["roles"].append({"id": "auditor", "name": "Auditor", "status": "proposed", "provenance": USER})
    v2 = stamp_revisions(v1, load_spec(raw2), 2)
    by_id = {p.id: p for p in v2.personas}
    assert by_id["approver"].revision.created_in == 1
    assert by_id["approver"].revision.updated_in == 2
    assert by_id["ops-analyst"].revision.updated_in == 1
    assert {r.id: r.revision.created_in for r in v2.roles}["auditor"] == 2
    assert v2.objective.revision.updated_in == 1


def test_client_supplied_revision_metadata_is_overwritten(raw: dict[str, Any]) -> None:
    raw["personas"][0]["revision"] = {"created_in": 99, "updated_in": 99}
    stamped = stamp_revisions(None, load_spec(raw), 1)
    assert stamped.personas[0].revision.created_in == 1


def test_semantic_fingerprint_ignores_revision_stamps(raw: dict[str, Any]) -> None:
    spec = load_spec(raw)
    assert semantic_fingerprint(stamp_revisions(None, spec, 1)) == semantic_fingerprint(spec)
    assert content_hash(stamp_revisions(None, spec, 1)) != content_hash(spec)


def test_stamp_does_not_mutate_input(raw: dict[str, Any]) -> None:
    spec = load_spec(raw)
    before = canonical_json(spec)
    stamp_revisions(None, spec, 1)
    assert canonical_json(spec) == before


# --------------------------------------------------------------------------- summary


def test_summary_counts_what_is_present(raw: dict[str, Any]) -> None:
    summary = summarize(load_spec(raw))
    personas = next(c for c in summary.collections if c.name == "personas")
    assert (personas.proposed, personas.confirmed) == (1, 1)
    assert summary.open_questions == 2
    assert summary.blocking_questions == 1
    statuses = {f.path: f.status for f in summary.facts}
    assert statuses["/objective"] is FactStatus.CONFIRMED
    assert statuses["/domain"] is FactStatus.PROPOSED
    assert statuses["/design_system/id"] is FactStatus.UNKNOWN
    assert summary.confirmed_facts == 2
