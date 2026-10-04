"""Canonical, versioned application specification (the project's source of truth)."""

from __future__ import annotations

import json
from typing import Any

from .common import FactStatus, ItemStatus, Provenance, RevisionMeta, Source, Tracked, TrackedItem
from .model import SCHEMA_VERSION, ApplicationSpec, ProjectMetadata
from .revisions import canonical_json, content_hash, semantic_fingerprint, stamp_revisions
from .summary import SpecSummary, summarize
from .validation import Severity, ValidationIssue, has_errors, validate_spec
from .versioning import SUPPORTED_VERSIONS, UnsupportedSchemaVersion, load_spec, migrate

__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_VERSIONS",
    "ApplicationSpec",
    "FactStatus",
    "ItemStatus",
    "ProjectMetadata",
    "Provenance",
    "RevisionMeta",
    "Severity",
    "Source",
    "SpecSummary",
    "Tracked",
    "TrackedItem",
    "UnsupportedSchemaVersion",
    "ValidationIssue",
    "canonical_json",
    "content_hash",
    "has_errors",
    "json_schema",
    "json_schema_text",
    "load_spec",
    "migrate",
    "semantic_fingerprint",
    "stamp_revisions",
    "summarize",
    "validate_spec",
]


def json_schema() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for the current spec version, for non-Python consumers."""
    schema = ApplicationSpec.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://github.com/joyrana/enterprise-ai-application-workspace/schemas/application-spec/{SCHEMA_VERSION}"
    schema["title"] = "ApplicationSpec"
    return schema


def json_schema_text() -> str:
    return json.dumps(json_schema(), indent=2, sort_keys=True) + "\n"
