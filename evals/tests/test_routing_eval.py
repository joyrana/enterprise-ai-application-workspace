"""Tests of the routing evaluation harness. Model behaviour is faked; only the lexical baseline is real."""

from __future__ import annotations

from model_gateway import ErrorKind, FakeProvider, ModelError
from workspace_evals.routing import Case, load_cases, markdown, metrics, predict, run


def test_dataset_is_balanced_and_valid() -> None:
    cases = load_cases()
    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases)
    labels = {c.expected for c in cases}
    assert labels == {"business-discovery", "acceptance-criteria", "requirements-conflict-detection", "none"}
    assert sum(c.expected == "none" for c in cases) >= 8


def test_lexical_baseline_is_deterministic() -> None:
    cases = load_cases()
    _, first = run(cases, "lexical", None)
    _, second = run(cases, "lexical", None)
    assert first == second
    assert first["model_calls"] == 0


def test_empty_spec_cases_route_without_a_model() -> None:
    case = Case(id="e", spec_state="empty", message="anything", expected="business-discovery")
    provider = FakeProvider([])
    prediction = predict(case, 0, "router", provider)
    assert prediction.predicted == "business-discovery"
    assert prediction.stage == "single-candidate"
    assert provider.requests == []


def test_router_method_uses_the_model_with_several_candidates() -> None:
    case = Case(
        id="c", spec_state="finance-example", message="contradictions?", expected="requirements-conflict-detection"
    )
    provider = FakeProvider([{"skill_id": "requirements-conflict-detection", "confidence": 0.8, "rationale": "r"}])
    prediction = predict(case, 0, "router", provider)
    assert prediction.predicted == "requirements-conflict-detection"
    assert prediction.model_calls == 1


def test_router_errors_are_counted_not_guessed() -> None:
    case = Case(id="c", spec_state="finance-example", message="x", expected="none")
    prediction = predict(case, 0, "router", FakeProvider([ModelError(ErrorKind.TIMEOUT)]))
    assert prediction.predicted is None
    assert prediction.error_kind == "timeout"
    m = metrics([prediction])
    assert m["accuracy"] == 0.0
    assert m["errors"] == {"timeout": 1}
    assert m["false_invocation_rate"] == 0.0


def test_metrics_precision_recall_and_rates() -> None:
    cases = [
        Case(id="1", spec_state="finance-example", message="a", expected="acceptance-criteria"),
        Case(id="2", spec_state="finance-example", message="b", expected="none"),
        Case(id="3", spec_state="finance-example", message="c", expected="none"),
    ]
    replies = iter(
        [
            {"skill_id": "acceptance-criteria", "confidence": 0.9, "rationale": "r"},
            {"skill_id": "business-discovery", "confidence": 0.5, "rationale": "r"},
            {"skill_id": "none", "confidence": 0.9, "rationale": "r"},
        ]
    )
    _, m = run(cases, "router", lambda: FakeProvider([next(replies)]))
    assert m["accuracy"] == round(2 / 3, 3)
    assert m["false_invocation_rate"] == 0.5
    assert m["per_label"]["acceptance-criteria"]["recall"] == 1.0
    assert m["confusion"] == {"none -> business-discovery": 1}


def test_schema_failures_keep_their_diagnostic_for_the_report() -> None:
    case = Case(id="c", spec_state="finance-example", message="contradictions?", expected="none")
    bad = {"skill_id": "conflicts", "confidence": 0.8, "rationale": "r"}  # not a listed id
    prediction = predict(case, 0, "router", FakeProvider([bad, bad]))
    assert prediction.error_kind == "schema_failure"
    assert prediction.error_detail is not None
    assert "skill_id" in prediction.error_detail
    m = metrics([prediction])
    assert m["error_details"][0]["case_id"] == "c"
    report = {
        "method": "router",
        "model": "fake",
        "dataset": "d",
        "repeats": 1,
        "router_prompt_version": "router@1",
        "run_at": "now",
        "metrics": m,
    }
    assert "skill_id" in markdown(report)


def test_variance_across_repeats_is_reported() -> None:
    case = Case(id="c", spec_state="finance-example", message="contradictions?", expected="none")
    replies = [
        {"skill_id": "none", "confidence": 0.8, "rationale": "r"},
        {"skill_id": "acceptance-criteria", "confidence": 0.6, "rationale": "r"},
    ]
    predictions, m = run([case], "router", lambda: FakeProvider([replies.pop(0)]), repeats=2)
    assert [p.repeat for p in predictions] == [0, 1]
    assert m["accuracy_by_repeat"] == [1.0, 0.0]
    assert m["accuracy_stdev"] == 0.5
    assert m["unstable_cases"] == ["c"]
