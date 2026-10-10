from __future__ import annotations

from codegen_react.merge import MARK_OURS, merge3, merge_projects, sha256

BASE = "".join(f"line {n}\n" for n in range(1, 11))


def edit(text: str, number: int, new: str) -> str:
    return text.replace(f"line {number}\n", new)


def test_one_sided_and_identical_changes_are_taken() -> None:
    assert merge3(BASE, BASE, BASE).text == BASE
    mine = edit(BASE, 2, "line 2 (mine)\n")
    gen = edit(BASE, 9, "line 9 (generated)\n")
    assert merge3(BASE, mine, BASE).text == mine
    assert merge3(BASE, BASE, gen).text == gen
    assert merge3(BASE, mine, mine).text == mine


def test_non_overlapping_edits_on_both_sides_merge_cleanly() -> None:
    mine = edit(BASE, 2, "line 2 (mine)\nan added line\n")
    gen = edit(edit(BASE, 8, "line 8 (generated)\n"), 10, "")
    merged = merge3(BASE, mine, gen)
    assert merged.conflicts == 0
    assert merged.text == (
        "line 1\nline 2 (mine)\nan added line\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8 (generated)\nline 9\n"
    )


def test_overlapping_different_edits_conflict_and_keep_both_sides() -> None:
    mine = edit(BASE, 5, "line 5 (mine)\n")
    gen = edit(BASE, 5, "line 5 (generated)\n")
    merged = merge3(BASE, mine, gen, label="regenerated r4")
    assert merged.conflicts == 1
    assert (
        f"line 4\n{MARK_OURS}\nline 5 (mine)\n=======\nline 5 (generated)\n>>>>>>> regenerated r4\nline 6\n"
        in merged.text
    )
    # Everything outside the conflict is intact.
    assert merged.text.startswith("line 1\nline 2\nline 3\nline 4\n")
    assert merged.text.endswith("line 9\nline 10\n")


def test_insertions_at_the_same_place_conflict_unless_identical() -> None:
    mine = edit(BASE, 3, "line 3\nmine\n")
    gen = edit(BASE, 3, "line 3\ngenerated\n")
    assert merge3(BASE, mine, gen).conflicts == 1
    assert merge3(BASE, mine, mine).text == mine


def test_deletion_versus_edit_conflicts() -> None:
    mine = edit(BASE, 6, "")
    gen = edit(BASE, 6, "line 6 (generated)\n")
    merged = merge3(BASE, mine, gen)
    assert merged.conflicts == 1
    assert "line 6 (generated)" in merged.text


def test_merge_is_deterministic_and_handles_missing_final_newline() -> None:
    mine = BASE + "tail without newline"
    gen = edit(BASE, 1, "first (generated)\n")
    first = merge3(BASE, mine, gen)
    assert first == merge3(BASE, mine, gen)
    assert first.text == "first (generated)\n" + BASE.split("\n", 1)[1] + "tail without newline"


def project(**files: str) -> dict[str, str]:
    return dict(files)


def test_project_upgrade_classifies_every_file() -> None:
    base = project(
        **{
            "a.ts": BASE,  # user edits line 2, generator edits line 9 -> merged
            "b.ts": BASE,  # user untouched, generator changes -> regenerated
            "c.ts": BASE,  # user changes, generator same -> kept
            "d.ts": BASE,  # both change line 5 -> conflict
            "e.ts": "old\n",  # generator drops, user untouched -> removed
            "f.ts": "old\n",  # generator drops, user changed -> orphaned
            "g.ts": BASE,  # user deleted, generator same -> deleted
            "h.ts": BASE,  # user deleted, generator changed -> restored
            "workspace-manifest.json": "{}",
        }
    )
    user = project(
        **{
            "a.ts": edit(BASE, 2, "mine\n"),
            "b.ts": BASE,
            "c.ts": edit(BASE, 3, "mine\n"),
            "d.ts": edit(BASE, 5, "mine\n"),
            "e.ts": "old\n",
            "f.ts": "changed\n",
            "notes.md": "my notes\n",
            "workspace-manifest.json": "{}",
        }
    )
    new = project(
        **{
            "a.ts": edit(BASE, 9, "gen\n"),
            "b.ts": edit(BASE, 1, "gen\n"),
            "c.ts": BASE,
            "d.ts": edit(BASE, 5, "gen\n"),
            "g.ts": BASE,
            "h.ts": edit(BASE, 4, "gen\n"),
            "z.ts": "new file\n",
            "workspace-manifest.json": '{"new": true}',
        }
    )
    hashes = {p: sha256(c) for p, c in base.items()}
    merged = merge_projects(user, new, base, hashes, "regenerated r3", frozenset({"workspace-manifest.json"}))
    status = {o.path: o.status for o in merged.outcomes}
    assert status == {
        "a.ts": "merged",
        "b.ts": "regenerated",
        "c.ts": "kept",
        "d.ts": "conflict",
        "e.ts": "removed",
        "f.ts": "orphaned",
        "g.ts": "deleted",
        "h.ts": "restored",
        "notes.md": "user-file",
        "z.ts": "added",
        "workspace-manifest.json": "regenerated",
    }
    assert merged.conflicts == 1
    assert "mine\n" in merged.files["a.ts"]
    assert "gen\n" in merged.files["a.ts"]
    assert merged.files["notes.md"] == "my notes\n"
    assert merged.files["workspace-manifest.json"] == '{"new": true}'
    assert "e.ts" not in merged.files
    assert "g.ts" not in merged.files
    assert merged.files["f.ts"] == "changed\n"


def test_without_a_reproducible_base_edited_files_are_kept_side_by_side() -> None:
    base_hashes = {"a.ts": sha256(BASE), "b.ts": sha256(BASE)}
    user = {"a.ts": edit(BASE, 2, "mine\n"), "b.ts": BASE}
    new = {"a.ts": edit(BASE, 9, "gen\n"), "b.ts": edit(BASE, 9, "gen\n")}
    merged = merge_projects(user, new, None, base_hashes, "regenerated r3")
    status = {o.path: o.status for o in merged.outcomes}
    assert status == {"a.ts": "side-by-side", "b.ts": "regenerated"}
    assert merged.files["a.ts"] == user["a.ts"]
    assert merged.files["a.ts.regenerated"] == new["a.ts"]
