"""Skill manifests, the execution context, and the skill protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from appspec import ApplicationSpec
from appspec.common import Identifier, LongText, ShortText
from model_gateway import Budget, ModelProvider, Prices

from .commands import AddItem, AddOpenQuestion, SetFact


class Risk(StrEnum):
    LOW = "low"  # proposals only; nothing changes without a human decision
    MEDIUM = "medium"
    HIGH = "high"  # external side effects or destructive changes; always needs approval


class Category(StrEnum):
    DISCOVERY = "discovery"
    EXPERIENCE_DESIGN = "experience-design"
    ARCHITECTURE = "architecture"
    DESIGN_SYSTEMS = "design-systems"
    ENGINEERING = "engineering"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_transport_retries: int = Field(default=2, ge=0, le=5)
    max_repairs: int = Field(default=1, ge=0, le=2)


class SkillManifest(BaseModel):
    """Everything the orchestrator needs to decide whether and how to run a skill."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    name: ShortText
    description: LongText
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    category: Category
    #: Intent phrases used by first-stage metadata filtering (never the sole routing signal).
    intents: tuple[ShortText, ...] = ()
    required_inputs: tuple[Identifier, ...] = ()
    optional_inputs: tuple[Identifier, ...] = ()
    #: Spec paths that must be known (proposed or confirmed) before the skill applies.
    preconditions: tuple[str, ...] = ()
    depends_on: tuple[Identifier, ...] = ()
    #: Tools the skill may call. Model access is the only tool in Milestone 2a.
    allowed_tools: tuple[Identifier, ...] = ("model",)
    risk: Risk = Risk.LOW
    uses_model: bool = True
    timeout_s: float = Field(default=180.0, gt=0, le=1800)
    max_model_calls: int = Field(default=2, ge=0, le=20)
    max_total_tokens: int = Field(default=40_000, ge=0)
    retry: RetryPolicy = RetryPolicy()
    prompt_version: str | None = None
    completion_criteria: LongText
    failure_behavior: LongText
    eval_suites: tuple[str, ...] = ()


@dataclass
class SkillContext:
    """What a running skill may use. It cannot reach the database or HTTP layer."""

    spec: ApplicationSpec
    provider: ModelProvider | None
    budget: Budget
    prices: Prices | None = None
    call_timeout_s: float = 60.0
    log: Callable[[str, dict[str, Any]], None] = field(default=lambda event, fields: None)


class SkillOutput(BaseModel):
    """Proposals plus evidence of how they were produced."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    proposals: list[SetFact | AddItem | AddOpenQuestion]
    #: True when the input was not a request to build an application (no proposals made).
    not_applicable_reason: str | None = None
    model: dict[str, Any] | None = None


class Skill(Protocol):
    manifest: ClassVar[SkillManifest]

    def run(self, context: SkillContext, inputs: dict[str, Any]) -> SkillOutput: ...
