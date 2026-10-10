"""Circuit breaker for model providers (Milestone 5, resilience).

Retries with jittered backoff (``OpenAICompatibleProvider``) handle a blip. When a provider
is down for longer, every run would still wait out its full timeout and keep hammering the
provider. The breaker fails fast instead:

- ``closed``: calls go through; consecutive *transient* failures (rate limits, unavailability,
  timeouts) are counted, and any success resets the count;
- ``open``: after ``failure_threshold`` such failures, calls fail immediately with
  ``provider_unavailable`` and a ``retry_after_s`` hint, for ``cooldown_s``;
- ``half_open``: after the cooldown, exactly one trial call goes through. Success closes the
  circuit; a transient failure opens it again for another cooldown.

Non-transient errors (bad credentials, bad request, schema failures) never trip the breaker:
they are not about availability. Thread-safe; the clock is injectable for tests.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any, Literal

from .errors import ErrorKind, ModelError
from .provider import ModelProvider, RawCompletion
from .schema import Capabilities, Message

State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(
        self, failure_threshold: int = 5, cooldown_s: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if failure_threshold < 1 or cooldown_s <= 0:
            raise ValueError("failure_threshold must be >= 1 and cooldown_s > 0")
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False

    @property
    def state(self) -> State:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> State:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.cooldown_s:
            return "half_open"
        return "open"

    def before_call(self) -> None:
        """Raise ``ModelError(UNAVAILABLE)`` without calling the provider when the circuit is open."""
        with self._lock:
            state = self._state_locked()
            if state == "closed":
                return
            if state == "half_open" and not self._trial_in_flight:
                self._trial_in_flight = True
                return
            assert self._opened_at is not None
            wait = max(0.0, self.cooldown_s - (self._clock() - self._opened_at))
            raise ModelError(
                ErrorKind.UNAVAILABLE,
                f"circuit open after {self._failures} consecutive provider failures; not calling the provider",
                retry_after_s=round(wait, 1) if wait else self.cooldown_s,
            )

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False

    def record_failure(self, error: ModelError) -> None:
        with self._lock:
            was_trial = self._trial_in_flight
            self._trial_in_flight = False
            if not error.kind.transient:
                return
            self._failures += 1
            if was_trial or self._failures >= self.failure_threshold:
                self._opened_at = self._clock()


class GuardedProvider:
    """A ``ModelProvider`` that consults a shared ``CircuitBreaker`` around every call."""

    def __init__(self, inner: ModelProvider, breaker: CircuitBreaker) -> None:
        self._inner = inner
        self._breaker = breaker

    @property
    def profile(self) -> str:
        return self._inner.profile

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    @property
    def capabilities(self) -> Capabilities:
        return self._inner.capabilities

    def complete(
        self,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout_s: float,
    ) -> RawCompletion:
        self._breaker.before_call()
        try:
            result = self._inner.complete(
                messages, json_schema=json_schema, schema_name=schema_name, timeout_s=timeout_s
            )
        except ModelError as error:
            self._breaker.record_failure(error)
            raise
        except Exception:
            # Unexpected errors still end a half-open trial, so the circuit cannot get stuck.
            self._breaker.record_failure(ModelError(ErrorKind.UNAVAILABLE, "unexpected provider error"))
            raise
        self._breaker.record_success()
        return result

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()
