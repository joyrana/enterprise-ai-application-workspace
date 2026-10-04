"""Model configuration from environment variables (ADR-0007).

Secrets (``HF_TOKEN`` / ``MODEL_API_KEY``) stay server-side and are redacted
from ``repr``. An unset ``MODEL_PROFILE`` means "no model configured": AI
features report that clearly instead of failing obscurely or faking results.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum

from .openai_compat import OpenAICompatibleProvider
from .provider import Prices
from .schema import Capabilities, StructuredMode


class Profile(StrEnum):
    HF_ROUTER = "hf-router"
    SELF_HOSTED = "self-hosted"
    OLLAMA = "ollama"


_DEFAULT_BASE_URL = {
    Profile.HF_ROUTER: "https://router.huggingface.co/v1",
    Profile.OLLAMA: "http://localhost:11434/v1",
}
_DEFAULT_REMOTE = {Profile.HF_ROUTER: True, Profile.SELF_HOSTED: False, Profile.OLLAMA: False}


class ModelConfigError(ValueError):
    pass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelSettings:
    profile: Profile
    base_url: str
    model_id: str
    api_key: str | None = field(default=None, repr=False)
    structured_mode: StructuredMode = StructuredMode.PROMPT_AND_VALIDATE
    remote: bool = True
    timeout_s: float = 60.0
    max_retries: int = 2
    max_output_tokens: int = 2048
    temperature: float = 0.0
    seed: int | None = None
    prices: Prices | None = None
    #: Allow confidential/restricted projects to use a remote model. Off by default.
    allow_remote_for_confidential: bool = False

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ModelConfigError("MODEL_ID is required when MODEL_PROFILE is set")
        if not self.base_url.startswith(("http://", "https://")):
            raise ModelConfigError("MODEL_BASE_URL must be an http(s) URL")
        if self.remote and self.base_url.startswith("http://"):
            raise ModelConfigError("remote model endpoints must use https")
        if not 0 <= self.max_retries <= 5:
            raise ModelConfigError("MODEL_MAX_RETRIES must be between 0 and 5")
        if not 1 <= self.timeout_s <= 600:
            raise ModelConfigError("MODEL_TIMEOUT_SECONDS must be between 1 and 600")

    @property
    def label(self) -> str:
        return f"{self.profile.value}:{self.model_id}"

    def capabilities(self) -> Capabilities:
        return Capabilities(structured_mode=self.structured_mode, remote=self.remote)

    def build_provider(self) -> OpenAICompatibleProvider:
        return OpenAICompatibleProvider(
            profile=self.profile.value,
            base_url=self.base_url,
            model_id=self.model_id,
            capabilities=self.capabilities(),
            api_key=self.api_key,
            max_retries=self.max_retries,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            seed=self.seed,
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ModelSettings | None:
        source = dict(os.environ if env is None else env)
        raw_profile = source.get("MODEL_PROFILE", "").strip()
        if not raw_profile:
            return None
        try:
            profile = Profile(raw_profile)
        except ValueError as exc:
            raise ModelConfigError(f"MODEL_PROFILE must be one of {[p.value for p in Profile]}") from exc
        base_url = source.get("MODEL_BASE_URL", "").strip() or _DEFAULT_BASE_URL.get(profile, "")
        if not base_url:
            raise ModelConfigError("MODEL_BASE_URL is required for the self-hosted profile")
        api_key = source.get("MODEL_API_KEY") or (source.get("HF_TOKEN") if profile is Profile.HF_ROUTER else None)
        if profile is Profile.HF_ROUTER and not api_key:
            raise ModelConfigError("HF_TOKEN is required for the hf-router profile")
        remote = _truthy(source["MODEL_REMOTE"]) if "MODEL_REMOTE" in source else _DEFAULT_REMOTE[profile]
        try:
            mode = StructuredMode(source.get("MODEL_STRUCTURED_MODE", StructuredMode.PROMPT_AND_VALIDATE.value))
            timeout = float(source.get("MODEL_TIMEOUT_SECONDS", "60"))
            retries = int(source.get("MODEL_MAX_RETRIES", "2"))
            max_tokens = int(source.get("MODEL_MAX_OUTPUT_TOKENS", "2048"))
            temperature = float(source.get("MODEL_TEMPERATURE", "0"))
            seed = int(source["MODEL_SEED"]) if source.get("MODEL_SEED") else None
            price_in = source.get("MODEL_PRICE_INPUT_PER_MTOK")
            price_out = source.get("MODEL_PRICE_OUTPUT_PER_MTOK")
            prices = Prices(float(price_in), float(price_out)) if price_in and price_out else None
        except ValueError as exc:
            raise ModelConfigError(f"invalid model configuration: {exc}") from exc
        return cls(
            profile=profile,
            base_url=base_url,
            model_id=source.get("MODEL_ID", ""),
            api_key=api_key,
            structured_mode=mode,
            remote=remote,
            timeout_s=timeout,
            max_retries=retries,
            max_output_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            prices=prices,
            allow_remote_for_confidential=_truthy(source.get("ALLOW_REMOTE_MODELS_FOR_CONFIDENTIAL")),
        )
