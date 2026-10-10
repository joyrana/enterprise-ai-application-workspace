"""Edit preservation: upgrade a hand-edited generated project to a newer spec revision (Milestone 5).

Three inputs per file:

- *base*: what the generator produced for the revision the user started from;
- *theirs*: the user's current file (their edits);
- *ours*: what the generator produces now.

Changes on only one side are taken as they are; identical changes on both sides are taken
once; overlapping different changes become a conflict, marked inline the way Git does, so
nothing a person wrote is ever silently dropped. Standard library only, deterministic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

FileStatus = Literal[
    "unchanged",  # nobody changed it
    "regenerated",  # only the generator changed it
    "kept",  # only the user changed it
    "merged",  # both changed it, without overlap
    "conflict",  # both changed the same lines differently; markers inserted
    "added",  # new generated file
    "user-file",  # a file the user added; kept as is
    "removed",  # no longer generated, and the user had not changed it
    "orphaned",  # no longer generated, but the user had changed it; kept
    "deleted",  # the user deleted it and the generator did not change it; stays deleted
    "restored",  # the user deleted it but the generator changed it; restored for review
    "side-by-side",  # no base available; the user's file is kept, the new one written next to it
]

MARK_OURS = "<<<<<<< your edit"
MARK_SPLIT = "======="


def _marker_end(label: str) -> str:
    return f">>>>>>> {label}"


@dataclass
class MergeResult:
    text: str
    conflicts: int = 0


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _changes(base: Sequence[str], other: Sequence[str]) -> list[tuple[int, int, list[str]]]:
    """Edits turning ``base`` into ``other``: (base_start, base_end, replacement lines)."""
    matcher = SequenceMatcher(a=base, b=other, autojunk=False)
    return [(i1, i2, list(other[j1:j2])) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal"]


def merge3(base: str, theirs: str, ours: str, label: str = "regenerated") -> MergeResult:
    """Merge the user's edits (``theirs``) and the generator's changes (``ours``) relative to ``base``."""
    if theirs == ours:
        return MergeResult(theirs)
    if theirs == base:
        return MergeResult(ours)
    if ours == base:
        return MergeResult(theirs)
    b = _lines(base)
    mine = _changes(b, _lines(theirs))
    gen = _changes(b, _lines(ours))
    out: list[str] = []
    conflicts = 0
    pos = 0
    i = j = 0
    while i < len(mine) or j < len(gen):
        # Take the next change, grouping every change from either side that overlaps it.
        if j >= len(gen) or (i < len(mine) and mine[i][0] <= gen[j][0]):
            start, end = mine[i][0], mine[i][1]
        else:
            start, end = gen[j][0], gen[j][1]
        group_mine: list[tuple[int, int, list[str]]] = []
        group_gen: list[tuple[int, int, list[str]]] = []
        grew = True
        while grew:
            grew = False
            while i < len(mine) and _overlaps(mine[i], start, end):
                start, end = min(start, mine[i][0]), max(end, mine[i][1])
                group_mine.append(mine[i])
                i += 1
                grew = True
            while j < len(gen) and _overlaps(gen[j], start, end):
                start, end = min(start, gen[j][0]), max(end, gen[j][1])
                group_gen.append(gen[j])
                j += 1
                grew = True
        out.extend(b[pos:start])
        mine_text = _apply(b, start, end, group_mine)
        gen_text = _apply(b, start, end, group_gen)
        if not group_gen:
            out.extend(mine_text)
        elif not group_mine or mine_text == gen_text:
            out.extend(gen_text)
        else:
            conflicts += 1
            out.append(MARK_OURS + "\n")
            out.extend(_terminated(mine_text))
            out.append(MARK_SPLIT + "\n")
            out.extend(_terminated(gen_text))
            out.append(_marker_end(label) + "\n")
        pos = end
    out.extend(b[pos:])
    return MergeResult("".join(out), conflicts)


def _overlaps(change: tuple[int, int, list[str]], start: int, end: int) -> bool:
    """Changes that overlap or merely touch are merged as one region: adjacent edits by both sides
    become a conflict for a person to review rather than a guess (conservative, like Git)."""
    c_start, c_end, _ = change
    return c_start <= end and start <= c_end


def _apply(base: Sequence[str], start: int, end: int, changes: list[tuple[int, int, list[str]]]) -> list[str]:
    """``base[start:end]`` with ``changes`` (sorted, non-overlapping, within the range) applied."""
    out: list[str] = []
    pos = start
    for c_start, c_end, lines in changes:
        out.extend(base[pos:c_start])
        out.extend(lines)
        pos = c_end
    out.extend(base[pos:end])
    return out


def _terminated(lines: list[str]) -> list[str]:
    if lines and not lines[-1].endswith("\n"):
        return [*lines[:-1], lines[-1] + "\n"]
    return lines


# --------------------------------------------------------------------------- whole projects


@dataclass
class FileOutcome:
    path: str
    status: FileStatus
    conflicts: int = 0
    note: str | None = None


@dataclass
class ProjectMerge:
    files: dict[str, str] = field(default_factory=dict)
    outcomes: list[FileOutcome] = field(default_factory=list)

    @property
    def conflicts(self) -> int:
        return sum(o.conflicts for o in self.outcomes)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def merge_projects(
    user: dict[str, str],
    new: dict[str, str],
    base: dict[str, str] | None,
    base_hashes: dict[str, str],
    label: str,
    generated_only: frozenset[str] = frozenset(),
) -> ProjectMerge:
    """Upgrade the user's project to ``new``.

    ``base`` is the exact generated project the user started from, when it can be reproduced
    (same generator version). Without it, ``base_hashes`` from the user's manifest still tell
    which files the user left untouched; changed files are then kept and the regenerated
    version is written next to them as ``<path>.regenerated`` for a manual merge.
    ``generated_only`` paths (the manifest) always take the new version.
    """
    result = ProjectMerge()
    for path in sorted(set(user) | set(new) | set(base_hashes)):
        in_user, in_new = path in user, path in new
        was_generated = path in base_hashes
        if path in generated_only:
            if in_new:
                result.files[path] = new[path]
                result.outcomes.append(FileOutcome(path, "regenerated"))
            continue
        user_untouched = in_user and was_generated and sha256(user[path]) == base_hashes[path]

        if not was_generated:
            if in_user and in_new:
                if user[path] == new[path]:
                    result.files[path] = new[path]
                    result.outcomes.append(FileOutcome(path, "unchanged"))
                else:
                    merged = merge3("", user[path], new[path], label)
                    result.files[path] = merged.text
                    result.outcomes.append(
                        FileOutcome(path, "conflict", max(1, merged.conflicts), "you and the generator both added it")
                    )
            elif in_user:
                result.files[path] = user[path]
                result.outcomes.append(FileOutcome(path, "user-file"))
            else:
                result.files[path] = new[path]
                result.outcomes.append(FileOutcome(path, "added"))
            continue

        if not in_new:
            if in_user and not user_untouched:
                result.files[path] = user[path]
                result.outcomes.append(FileOutcome(path, "orphaned", note="no longer generated; your version is kept"))
            elif in_user:
                result.outcomes.append(FileOutcome(path, "removed"))
            continue

        if not in_user:
            generator_changed = sha256(new[path]) != base_hashes[path]
            if generator_changed:
                result.files[path] = new[path]
                result.outcomes.append(FileOutcome(path, "restored", note="you deleted it; the generator changed it"))
            else:
                result.outcomes.append(FileOutcome(path, "deleted"))
            continue

        if user_untouched:
            same = sha256(new[path]) == base_hashes[path]
            result.files[path] = new[path]
            result.outcomes.append(FileOutcome(path, "unchanged" if same else "regenerated"))
            continue

        # The user changed the file.
        if sha256(new[path]) == base_hashes[path]:
            result.files[path] = user[path]
            result.outcomes.append(FileOutcome(path, "kept"))
        elif base is not None and path in base:
            merged = merge3(base[path], user[path], new[path], label)
            result.files[path] = merged.text
            result.outcomes.append(FileOutcome(path, "conflict" if merged.conflicts else "merged", merged.conflicts))
        else:
            result.files[path] = user[path]
            result.files[f"{path}.regenerated"] = new[path]
            result.outcomes.append(
                FileOutcome(
                    path,
                    "side-by-side",
                    1,
                    "made by another generator version; compare with the .regenerated file",
                )
            )
    return result
