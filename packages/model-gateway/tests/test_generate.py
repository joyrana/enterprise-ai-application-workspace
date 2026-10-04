from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from model_gateway import (
    Budget,
    Capabilities,
    ErrorKind,
    FakeProvider,
    Message,
    ModelError,
    Prices,
    StructuredMode,
    Usage,
    check_data_policy,
    generate_structured,
)


class Answer(BaseModel):
    title: str = Field(min_length=1)
    count: int = Field(ge=0)


MESSAGES = [Message(role="system", content="You are helpful."), Message(role="user", content="Go")]


def test_valid_first_answer() -> None:
    provider = FakeProvider([{"title": "x", "count": 2}])
    result = generate_structured(provider, MESSAGES, Answer, budget=Budget())
    assert result.value == Answer(title="x", count=2)
    assert result.repaired is False
    assert [c.outcome for c in result.calls] == ["ok"]
    assert result.usage == Usage(prompt_tokens=100, completion_tokens=50)
    assert result.estimated_cost_usd is None  # never guessed


def test_schema_is_added_to_the_system_prompt_and_user_text_untouched() -> None:
    provider = FakeProvider([{"title": "x", "count": 0}])
    generate_structured(provider, MESSAGES, Answer, budget=Budget())
    sent = provider.requests[0]
    assert sent[0].role == "system"
    assert "<json_schema>" in sent[0].content
    assert sent[0].content.startswith("You are helpful.")
    assert sent[1] == MESSAGES[1]
    assert provider.schemas == [None]  # prompt_and_validate: no server-side schema


def test_native_json_schema_mode_passes_schema() -> None:
    provider = FakeProvider(
        [{"title": "x", "count": 0}], capabilities=Capabilities(structured_mode=StructuredMode.JSON_SCHEMA)
    )
    generate_structured(provider, MESSAGES, Answer, budget=Budget())
    assert provider.schemas[0] is not None
    assert provider.schemas[0]["title"] == "Answer"


def test_one_repair_with_validation_feedback() -> None:
    provider = FakeProvider(['Sure! {"title": "", "count": -1}', {"title": "fixed", "count": 1}])
    result = generate_structured(provider, MESSAGES, Answer, budget=Budget())
    assert result.value.title == "fixed"
    assert result.repaired is True
    assert [c.outcome for c in result.calls] == ["schema_failure", "ok"]
    assert [c.purpose for c in result.calls] == ["initial", "repair"]
    feedback = provider.requests[1][-1].content
    assert "/title" in feedback
    assert "/count" in feedback
    assert result.usage.total_tokens == 300


def test_schema_failure_after_repair_budget() -> None:
    provider = FakeProvider(["not json", "still not json"])
    with pytest.raises(ModelError) as info:
        generate_structured(provider, MESSAGES, Answer, budget=Budget())
    assert info.value.kind is ErrorKind.SCHEMA_FAILURE
    assert [c.outcome for c in info.value.calls] == ["schema_failure", "schema_failure"]


def test_no_repair_when_disabled() -> None:
    provider = FakeProvider(["nope"])
    with pytest.raises(ModelError, match="schema_failure"):
        generate_structured(provider, MESSAGES, Answer, budget=Budget(), max_repairs=0)


def test_provider_errors_propagate_with_call_record() -> None:
    provider = FakeProvider([ModelError(ErrorKind.AUTH, "HTTP 401")])
    with pytest.raises(ModelError) as info:
        generate_structured(provider, MESSAGES, Answer, budget=Budget())
    assert info.value.kind is ErrorKind.AUTH
    assert info.value.calls[0].outcome == "error"
    assert info.value.calls[0].error_kind == "auth"
    assert "credentials" in info.value.user_message


def test_call_budget_stops_repair() -> None:
    provider = FakeProvider(["bad", {"title": "x", "count": 1}])
    with pytest.raises(ModelError) as info:
        generate_structured(provider, MESSAGES, Answer, budget=Budget(max_calls=1))
    assert info.value.kind is ErrorKind.BUDGET_EXCEEDED


def test_token_budget() -> None:
    budget = Budget(max_total_tokens=100)
    budget.record(Usage(prompt_tokens=80, completion_tokens=30))
    with pytest.raises(ModelError, match="token limit"):
        budget.check()


def test_deadline_budget() -> None:
    now = [0.0]
    budget = Budget(deadline_s=10, clock=lambda: now[0])
    budget.check()
    now[0] = 10.5
    with pytest.raises(ModelError, match="deadline"):
        budget.check()


def test_cost_only_with_configured_prices() -> None:
    provider = FakeProvider([{"title": "x", "count": 1}])
    result = generate_structured(
        provider, MESSAGES, Answer, budget=Budget(), prices=Prices(input_per_mtok=1.0, output_per_mtok=2.0)
    )
    assert result.estimated_cost_usd == pytest.approx(100 / 1e6 + 100 / 1e6)


@pytest.mark.parametrize(
    ("remote", "classification", "allowed"),
    [
        (True, "confidential", False),
        (True, "restricted", False),
        (True, "internal", True),
        (True, None, True),
        (False, "restricted", True),
    ],
)
def test_data_policy(remote: bool, classification: str | None, allowed: bool) -> None:
    caps = Capabilities(remote=remote)
    if allowed:
        check_data_policy(caps, classification, allow_remote=False)
    else:
        with pytest.raises(ModelError) as info:
            check_data_policy(caps, classification, allow_remote=False)
        assert info.value.kind is ErrorKind.POLICY_DENIED


def test_data_policy_operator_override() -> None:
    check_data_policy(Capabilities(remote=True), "confidential", allow_remote=True)
