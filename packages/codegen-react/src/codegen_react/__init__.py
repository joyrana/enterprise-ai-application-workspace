"""Deterministic React + Fluent 2 code generation (ADR-0014)."""

from .diff import FileDiff, diff_projects
from .generate import (
    GENERATOR,
    GENERATOR_VERSION,
    MANIFEST,
    GeneratedProject,
    GenerationBlocked,
    generate_project,
    package_name,
    pascal,
    toolchain,
)
from .jsx import ALLOWED, GenerationError, literal

__all__ = [
    "ALLOWED",
    "GENERATOR",
    "GENERATOR_VERSION",
    "MANIFEST",
    "FileDiff",
    "GeneratedProject",
    "GenerationBlocked",
    "GenerationError",
    "diff_projects",
    "generate_project",
    "literal",
    "package_name",
    "pascal",
    "toolchain",
]
