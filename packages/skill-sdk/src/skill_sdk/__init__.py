"""Skill contracts, registry and typed specification commands."""

from .commands import (
    FACT_PATHS,
    ITEM_COLLECTIONS,
    AddItem,
    AddOpenQuestion,
    CommandResult,
    Decision,
    Outcome,
    SetFact,
    SpecCommand,
    apply_commands,
)
from .ids import IdAllocator, slugify
from .registry import RegistryError, SkillRegistry, unmet_preconditions
from .router import NONE, ROUTER_PROMPT_VERSION, RouteDecision, RoutingError, SkillRouter, lexical_choice
from .skill import Category, RetryPolicy, Risk, Skill, SkillContext, SkillManifest, SkillOutput

__all__ = [
    "FACT_PATHS",
    "ITEM_COLLECTIONS",
    "NONE",
    "ROUTER_PROMPT_VERSION",
    "AddItem",
    "AddOpenQuestion",
    "Category",
    "CommandResult",
    "Decision",
    "IdAllocator",
    "Outcome",
    "RegistryError",
    "RetryPolicy",
    "Risk",
    "RouteDecision",
    "RoutingError",
    "SetFact",
    "Skill",
    "SkillContext",
    "SkillManifest",
    "SkillOutput",
    "SkillRegistry",
    "SkillRouter",
    "SpecCommand",
    "apply_commands",
    "lexical_choice",
    "slugify",
    "unmet_preconditions",
]
