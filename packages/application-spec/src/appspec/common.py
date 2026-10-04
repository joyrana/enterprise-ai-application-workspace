"""Shared building blocks for the canonical application specification.

The specification distinguishes *what is known* from *how it became known*:

* ``status`` says whether a fact is unknown, proposed (not yet approved), or
  confirmed (approved by a named user).
* ``provenance`` says where it came from: the user, a model-backed skill,
  deterministic derivation, or the system itself.
* ``revision`` is stamped by the server and records the project revision in
  which an element was introduced and last changed.

Unknown values are represented explicitly (``status="unknown"`` with no value)
instead of being filled with invented business facts.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

T = TypeVar("T")

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$"),
    Field(description="Stable, human-readable identifier (lowercase kebab-case, max 64 chars)."),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class StrictModel(BaseModel):
    """Base model: unknown fields are rejected so typos never silently vanish."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FactStatus(StrEnum):
    UNKNOWN = "unknown"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class ItemStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"


class Source(StrEnum):
    USER = "user"
    MODEL = "model"
    DERIVED = "derived"
    SYSTEM = "system"


class Provenance(StrictModel):
    """Where a value came from. Model-sourced values record the producing skill and model."""

    source: Source
    actor: ShortText | None = Field(default=None, description="User or service identity that supplied the value.")
    skill_id: Identifier | None = None
    skill_version: ShortText | None = None
    model_id: ShortText | None = None
    prompt_version: ShortText | None = None
    note: LongText | None = None

    @model_validator(mode="after")
    def _model_source_needs_skill(self) -> Self:
        if self.source is Source.MODEL and (self.skill_id is None or self.model_id is None):
            raise ValueError("model-sourced provenance must record skill_id and model_id")
        return self


class RevisionMeta(StrictModel):
    """Server-stamped revision bookkeeping. Client-supplied values are overwritten."""

    created_in: int | None = Field(default=None, ge=1)
    updated_in: int | None = Field(default=None, ge=1)


def _check_status(status: str, has_value: bool, provenance: Provenance | None, confirmed_by: str | None) -> None:
    if status == FactStatus.UNKNOWN:
        if has_value:
            raise ValueError("an unknown fact must not carry a value")
        if confirmed_by is not None:
            raise ValueError("an unknown fact cannot be confirmed")
        return
    if not has_value:
        raise ValueError(f"a {status} fact must carry a value")
    if provenance is None:
        raise ValueError(f"a {status} fact must record its provenance")
    if status == FactStatus.CONFIRMED and confirmed_by is None:
        raise ValueError("a confirmed fact must record who confirmed it (confirmed_by)")
    if status == FactStatus.PROPOSED and confirmed_by is not None:
        raise ValueError("a proposed fact cannot have confirmed_by set")


class Tracked(StrictModel, Generic[T]):
    """A single scalar fact with explicit status and provenance."""

    value: T | None = None
    status: FactStatus = FactStatus.UNKNOWN
    provenance: Provenance | None = None
    confirmed_by: ShortText | None = None
    revision: RevisionMeta = Field(default_factory=RevisionMeta)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_status(self.status, self.value is not None, self.provenance, self.confirmed_by)
        return self


class TrackedItem(StrictModel):
    """Base for collection items (personas, requirements, screens, ...).

    An item that exists in the spec has been at least proposed, so ``unknown`` is
    not a valid item status; open questions model genuinely unknown things.
    """

    id: Identifier
    status: ItemStatus = ItemStatus.PROPOSED
    provenance: Provenance
    confirmed_by: ShortText | None = None
    revision: RevisionMeta = Field(default_factory=RevisionMeta)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_status(self.status, True, self.provenance, self.confirmed_by)
        return self
