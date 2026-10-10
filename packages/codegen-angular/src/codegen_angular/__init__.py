"""Deterministic Angular + Material 3 code generation from the UI IR (ADR-0017)."""

from .generate import GENERATOR, GENERATOR_VERSION, ScreenBuilder, generate_project, literal, toolchain
from .template import ATTRIBUTES, ELEMENTS

__all__ = [
    "ATTRIBUTES",
    "ELEMENTS",
    "GENERATOR",
    "GENERATOR_VERSION",
    "ScreenBuilder",
    "generate_project",
    "literal",
    "toolchain",
]
