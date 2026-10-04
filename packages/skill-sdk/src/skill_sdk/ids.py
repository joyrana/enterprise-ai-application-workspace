"""Deterministic, collision-free identifier generation for proposed spec elements."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_MAX = 64


def slugify(text: str, *, fallback: str = "item", max_length: int = 48) -> str:
    """Lowercase kebab-case identifier matching appspec's Identifier pattern."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _NON_ALNUM.sub("-", ascii_text.lower()).strip("-")[:max_length].strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"{fallback}-{slug}" if slug else fallback
    return slug[:max_length].strip("-")


class IdAllocator:
    """Allocates ids unique across the spec's shared namespace and this batch."""

    def __init__(self, taken: Iterable[str]) -> None:
        self._taken = set(taken)

    def allocate(self, text: str, *, prefix: str | None = None, fallback: str = "item") -> str:
        base = slugify(text, fallback=fallback)
        if prefix and not base.startswith(f"{prefix}-"):
            base = f"{prefix}-{base}"[:48].strip("-")
        candidate = base
        counter = 2
        while candidate in self._taken:
            suffix = f"-{counter}"
            candidate = f"{base[: _MAX - len(suffix)]}{suffix}"
            counter += 1
        self._taken.add(candidate)
        return candidate
