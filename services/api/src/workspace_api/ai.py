"""Model runtime wiring for the API process.

Built once at startup from environment variables (``model_gateway.ModelSettings``).
When no model is configured, AI endpoints answer with a clear 503 instead of
failing obscurely; nothing ever pretends a model ran.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from model_gateway import Capabilities, CircuitBreaker, GuardedProvider, ModelProvider, ModelSettings, Prices


@dataclass(frozen=True)
class ModelRuntime:
    label: str
    profile: str
    model_id: str
    capabilities: Capabilities
    factory: Callable[[], ModelProvider]
    allow_remote_for_confidential: bool = False
    call_timeout_s: float = 60.0
    prices: Prices | None = None
    #: Shared by every run in this process: fails fast while the provider is down (Milestone 5).
    breaker: CircuitBreaker | None = field(default=None, compare=False)

    def provider(self) -> ModelProvider:
        """A provider for one run, guarded by the shared circuit breaker when there is one."""
        inner = self.factory()
        return GuardedProvider(inner, self.breaker) if self.breaker is not None else inner

    @classmethod
    def from_settings(cls, settings: ModelSettings) -> ModelRuntime:
        return cls(
            label=settings.label,
            profile=settings.profile.value,
            model_id=settings.model_id,
            capabilities=settings.capabilities(),
            factory=settings.build_provider,
            allow_remote_for_confidential=settings.allow_remote_for_confidential,
            call_timeout_s=settings.timeout_s,
            prices=settings.prices,
            breaker=CircuitBreaker(failure_threshold=5, cooldown_s=30.0),
        )

    @classmethod
    def from_env(cls) -> ModelRuntime | None:
        settings = ModelSettings.from_env()
        return cls.from_settings(settings) if settings else None
