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
from .merge import FileOutcome, MergeResult, ProjectMerge, merge3, merge_projects

__all__ = [
    "ALLOWED",
    "GENERATOR",
    "GENERATOR_VERSION",
    "MANIFEST",
    "FileDiff",
    "FileOutcome",
    "GeneratedProject",
    "GenerationBlocked",
    "GenerationError",
    "MergeResult",
    "ProjectMerge",
    "diff_projects",
    "generate_project",
    "literal",
    "merge3",
    "merge_projects",
    "package_name",
    "pascal",
    "toolchain",
]
