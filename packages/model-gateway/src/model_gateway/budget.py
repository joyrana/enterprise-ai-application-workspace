"""Workflow-level budgets: model calls, tokens and wall-clock deadline."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .errors import ErrorKind, ModelError
from .schema import Usage


@dataclass
class Budget:
    max_calls: int = 4
    max_total_tokens: int = 60_000
    deadline_s: float = 180.0
    clock: Callable[[], float] = time.monotonic
    calls: int = 0
    usage: Usage = field(default_factory=Usage)
    _started: float | None = None

    def __post_init__(self) -> None:
        if self.max_calls < 1 or self.max_total_tokens < 1 or self.deadline_s <= 0:
            raise ValueError("budget limits must be positive")
        self._started = self.clock()

    @property
    def remaining_s(self) -> float:
        assert self._started is not None
        return self.deadline_s - (self.clock() - self._started)

    def check(self) -> None:
        """Raise before starting a call that the budget does not allow."""
        if self.calls >= self.max_calls:
            raise ModelError(ErrorKind.BUDGET_EXCEEDED, f"call limit {self.max_calls} reached")
        if self.usage.total_tokens >= self.max_total_tokens:
            raise ModelError(ErrorKind.BUDGET_EXCEEDED, f"token limit {self.max_total_tokens} reached")
        if self.remaining_s <= 0:
            raise ModelError(ErrorKind.BUDGET_EXCEEDED, f"deadline of {self.deadline_s:.0f}s reached")

    def record(self, usage: Usage) -> None:
        self.calls += 1
        self.usage = self.usage + usage
