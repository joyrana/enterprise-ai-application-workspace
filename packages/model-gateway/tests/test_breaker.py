from __future__ import annotations

import threading
from typing import Any

import pytest

from model_gateway import CircuitBreaker, ErrorKind, GuardedProvider, ModelError


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Flaky:
    """Fails with the queued errors, then succeeds."""

    profile = "fake"
    model_id = "flaky"
    capabilities: Any = None

    def __init__(self, errors: list[ModelError]) -> None:
        self.errors = errors
        self.calls = 0

    def complete(self, messages: Any, *, json_schema: Any, schema_name: str, timeout_s: float) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def unavailable() -> ModelError:
    return ModelError(ErrorKind.UNAVAILABLE, "HTTP 503 from provider")


def call(provider: GuardedProvider) -> Any:
    return provider.complete([], json_schema=None, schema_name="x", timeout_s=5)


def test_opens_after_consecutive_transient_failures_and_fails_fast() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=3, cooldown_s=30, clock=clock)
    inner = Flaky([unavailable() for _ in range(10)])
    provider = GuardedProvider(inner, breaker)  # type: ignore[arg-type]
    for _ in range(3):
        with pytest.raises(ModelError):
            call(provider)
    assert breaker.state == "open"
    with pytest.raises(ModelError) as info:
        call(provider)
    assert info.value.kind is ErrorKind.UNAVAILABLE
    assert "circuit open" in str(info.value)
    assert info.value.retry_after_s == 30
    assert inner.calls == 3  # the provider was not called while open


def test_half_open_trial_closes_on_success_and_reopens_on_failure() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=2, cooldown_s=10, clock=clock)
    inner = Flaky([unavailable(), unavailable(), unavailable()])
    provider = GuardedProvider(inner, breaker)  # type: ignore[arg-type]
    for _ in range(2):
        with pytest.raises(ModelError):
            call(provider)
    clock.now += 10
    assert breaker.state == "half_open"
    with pytest.raises(ModelError):  # the trial fails: open again for a full cooldown
        call(provider)
    assert breaker.state == "open"
    clock.now += 9
    with pytest.raises(ModelError, match="circuit open"):
        call(provider)
    clock.now += 1
    assert call(provider) == "ok"  # the next trial succeeds
    assert breaker.state == "closed"


def test_success_resets_and_non_transient_errors_never_trip() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_s=10, clock=Clock())
    errors = [
        unavailable(),
        ModelError(ErrorKind.AUTH),
        ModelError(ErrorKind.SCHEMA_FAILURE),
        ModelError(ErrorKind.AUTH),
    ]
    provider = GuardedProvider(Flaky(errors), breaker)  # type: ignore[arg-type]
    for _ in range(4):
        with pytest.raises(ModelError):
            call(provider)
    assert breaker.state == "closed"  # one transient failure, then non-transient ones
    assert call(provider) == "ok"
    assert breaker.state == "closed"


def test_only_one_trial_runs_while_half_open() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, cooldown_s=5, clock=clock)
    breaker.record_failure(unavailable())
    clock.now += 5
    results: list[str] = []
    barrier = threading.Barrier(8)

    def attempt() -> None:
        barrier.wait()
        try:
            breaker.before_call()
            results.append("trial")
        except ModelError:
            results.append("rejected")

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("trial") == 1
    assert results.count("rejected") == 7


def test_rejects_invalid_settings() -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreaker(failure_threshold=0)
