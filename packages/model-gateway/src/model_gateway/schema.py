"""Typed contracts shared by every provider."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StructuredMode(StrEnum):
    """How a provider is asked for JSON. Declared per profile/model, never assumed.

    * ``json_schema`` — server-side constrained decoding against the schema.
    * ``json_object`` — JSON mode without schema enforcement.
    * ``prompt_and_validate`` — schema only in the prompt; the client parses and validates.

    In every mode the client still validates the result; the mode only changes
    what the server is asked to enforce.
    """

    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_AND_VALIDATE = "prompt_and_validate"


class Capabilities(Model):
    structured_mode: StructuredMode = StructuredMode.PROMPT_AND_VALIDATE
    supports_tools: bool = False
    context_window_tokens: int | None = Field(default=None, ge=1)
    #: Whether prompts leave the organization's network (affects the data-classification policy).
    remote: bool = True


class Message(Model):
    role: Literal["system", "user", "assistant"]
    content: str


class Usage(Model):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


class CallRecord(Model):
    """Telemetry for one HTTP call. Never contains prompt or completion text."""

    model_id: str
    profile: str
    purpose: Literal["initial", "repair"]
    transport_attempts: int = Field(ge=1)
    latency_ms: float = Field(ge=0)
    usage: Usage
    outcome: Literal["ok", "schema_failure", "error"]
    error_kind: str | None = None


class StructuredResult[T: BaseModel](BaseModel):
    """A validated structured result plus the evidence of how it was produced."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T
    model_id: str
    profile: str
    usage: Usage
    calls: list[CallRecord]
    repaired: bool
    estimated_cost_usd: float | None = Field(
        default=None, description="Only set when prices are configured; never guessed."
    )
