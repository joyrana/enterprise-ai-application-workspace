"""Canonical serialization, content hashing, and artifact-level revision stamping."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from .common import RevisionMeta
from .model import ApplicationSpec


def canonical_json(spec: ApplicationSpec) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace, UTF-8 safe."""
    return json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(spec: ApplicationSpec) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()


def _strip_revision(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_revision(v) for k, v in value.items() if k != "revision"}
    if isinstance(value, list):
        return [_strip_revision(v) for v in value]
    return value


def _fingerprint(model: BaseModel) -> str:
    return json.dumps(_strip_revision(model.model_dump(mode="json")), sort_keys=True, separators=(",", ":"))


def semantic_fingerprint(spec: ApplicationSpec) -> str:
    """Hash of the spec's meaning, ignoring server-stamped revision bookkeeping."""
    return "sha256:" + hashlib.sha256(_fingerprint(spec).encode("utf-8")).hexdigest()


def _revisioned(model: BaseModel, path: str) -> Iterator[tuple[str, BaseModel]]:
    """Yield (stable key, model) for every sub-model that carries a ``revision`` field.

    Items inside lists are keyed by their ``id`` so reordering a list does not
    count as a change.
    """
    if "revision" in type(model).model_fields and isinstance(getattr(model, "revision", None), RevisionMeta):
        yield path, model
    for name in type(model).model_fields:
        if name == "revision":
            continue
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            yield from _revisioned(value, f"{path}/{name}")
        elif isinstance(value, list):
            for index, element in enumerate(value):
                if isinstance(element, BaseModel):
                    key = getattr(element, "id", None)
                    suffix = f"[{key}]" if isinstance(key, str) else f"/{index}"
                    yield from _revisioned(element, f"{path}/{name}{suffix}")


def stamp_revisions(previous: ApplicationSpec | None, proposed: ApplicationSpec, revision: int) -> ApplicationSpec:
    """Return a copy of ``proposed`` with server-authoritative revision metadata.

    * New elements get ``created_in = updated_in = revision``.
    * Unchanged elements keep their previous metadata.
    * Changed elements keep ``created_in`` and get ``updated_in = revision``.

    Any revision metadata supplied by the client is discarded.
    """
    if revision < 1:
        raise ValueError("revision must be >= 1")
    before: dict[str, BaseModel] = dict(_revisioned(previous, "")) if previous is not None else {}
    result = proposed.model_copy(deep=True)
    for key, element in _revisioned(result, ""):
        old = before.get(key)
        if old is None:
            meta = RevisionMeta(created_in=revision, updated_in=revision)
        else:
            old_meta: RevisionMeta = old.revision  # type: ignore[attr-defined]
            if _fingerprint(old) == _fingerprint(element):
                meta = old_meta.model_copy()
            else:
                meta = RevisionMeta(created_in=old_meta.created_in or revision, updated_in=revision)
        element.revision = meta  # type: ignore[attr-defined]
    return result
