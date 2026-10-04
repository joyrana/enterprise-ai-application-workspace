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
from .registry import RegistryError, SkillRegistry
from .skill import Category, RetryPolicy, Risk, Skill, SkillContext, SkillManifest, SkillOutput

__all__ = [
    "FACT_PATHS",
    "ITEM_COLLECTIONS",
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
    "SetFact",
    "Skill",
    "SkillContext",
    "SkillManifest",
    "SkillOutput",
    "SkillRegistry",
    "SpecCommand",
    "apply_commands",
    "slugify",
]
