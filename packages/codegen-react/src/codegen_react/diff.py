"""File-level diff between two generated projects (for review before anyone takes the code)."""

from __future__ import annotations

import difflib
from typing import Literal

from pydantic import BaseModel

from .generate import GeneratedProject


class FileDiff(BaseModel):
    path: str
    status: Literal["added", "removed", "modified"]
    additions: int
    deletions: int
    unified: str


def diff_projects(old: GeneratedProject, new: GeneratedProject, *, context: int = 3) -> list[FileDiff]:
    out: list[FileDiff] = []
    for path in sorted(set(old.files) | set(new.files)):
        before, after = old.files.get(path), new.files.get(path)
        if before == after:
            continue
        status: Literal["added", "removed", "modified"] = (
            "added" if before is None else "removed" if after is None else "modified"
        )
        lines = list(
            difflib.unified_diff(
                (before or "").splitlines(keepends=True),
                (after or "").splitlines(keepends=True),
                fromfile=f"a/{path}" if before is not None else "/dev/null",
                tofile=f"b/{path}" if after is not None else "/dev/null",
                n=context,
            )
        )
        additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        out.append(FileDiff(path=path, status=status, additions=additions, deletions=deletions, unified="".join(lines)))
    return out
