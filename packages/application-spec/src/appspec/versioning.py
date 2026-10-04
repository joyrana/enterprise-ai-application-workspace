"""Schema versioning and forward migration of stored specifications.

Stored specs are never rewritten in place. When the schema evolves, add a
migration function ``vX -> vY`` to ``_MIGRATIONS``; ``load_spec`` applies the
chain on read so old revisions stay readable and auditable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .model import SCHEMA_VERSION, ApplicationSpec

Migration = Callable[[dict[str, Any]], dict[str, Any]]

#: from_version -> (to_version, migration). Empty while 1.0.0 is the only version.
_MIGRATIONS: dict[str, tuple[str, Migration]] = {}

SUPPORTED_VERSIONS: frozenset[str] = frozenset({SCHEMA_VERSION, *_MIGRATIONS})


class UnsupportedSchemaVersion(ValueError):
    def __init__(self, version: object) -> None:
        super().__init__(
            f"unsupported application-spec schema_version {version!r}; supported: {sorted(SUPPORTED_VERSIONS)}"
        )
        self.version = version


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a raw spec document to the current schema version without validating it."""
    version = raw.get("schema_version")
    if not isinstance(version, str) or version not in SUPPORTED_VERSIONS:
        raise UnsupportedSchemaVersion(version)
    doc = dict(raw)
    guard = 0
    while doc["schema_version"] != SCHEMA_VERSION:
        target, step = _MIGRATIONS[doc["schema_version"]]
        doc = step(doc)
        doc["schema_version"] = target
        guard += 1
        if guard > len(_MIGRATIONS):
            raise RuntimeError("migration chain does not terminate")
    return doc


def load_spec(raw: dict[str, Any]) -> ApplicationSpec:
    """Migrate (if needed) and validate a stored or submitted spec document."""
    return ApplicationSpec.model_validate(migrate(raw))
