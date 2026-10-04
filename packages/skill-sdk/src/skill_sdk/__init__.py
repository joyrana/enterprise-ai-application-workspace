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
from .safety import DETECTOR_VERSION, EchoFlag, ScanReport, Signal, SignalKind, flag_echoes, scan_text, untrusted_notice
from .skill import Category, RetryPolicy, Risk, Skill, SkillContext, SkillManifest, SkillOutput

__all__ = [
    "DETECTOR_VERSION",
    "FACT_PATHS",
    "ITEM_COLLECTIONS",
    "NONE",
    "ROUTER_PROMPT_VERSION",
    "AddItem",
    "AddOpenQuestion",
    "Category",
    "CommandResult",
    "Decision",
    "EchoFlag",
    "IdAllocator",
    "Outcome",
    "RegistryError",
    "RetryPolicy",
    "Risk",
    "RouteDecision",
    "RoutingError",
    "ScanReport",
    "SetFact",
    "Signal",
    "SignalKind",
    "Skill",
    "SkillContext",
    "SkillManifest",
    "SkillOutput",
    "SkillRegistry",
    "SkillRouter",
    "SpecCommand",
    "apply_commands",
    "flag_echoes",
    "lexical_choice",
    "scan_text",
    "slugify",
    "unmet_preconditions",
    "untrusted_notice",
]
