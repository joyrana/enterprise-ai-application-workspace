"""Model runtime wiring for the API process.

Built once at startup from environment variables (``model_gateway.ModelSettings``).
When no model is configured, AI endpoints answer with a clear 503 instead of
failing obscurely; nothing ever pretends a model ran.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from model_gateway import Capabilities, ModelProvider, ModelSettings, Prices


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
        )

    @classmethod
    def from_env(cls) -> ModelRuntime | None:
        settings = ModelSettings.from_env()
        return cls.from_settings(settings) if settings else None
