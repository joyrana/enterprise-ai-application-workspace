# ADR-0016: Edit preservation by three-way merge against a reproduced base

- Status: Accepted · Date: 2026-10-10

## Context

Generated projects are meant to be extended by hand: business logic, styling, extra files.
Until now, regenerating meant replacing everything (ADR-0014 said so in every file header).
Teams need to take a new specification revision without losing their work, and to see exactly
where their changes and the generator's changes collide.

Approaches considered:

- **Protected regions** (`// BEGIN USER CODE` markers): fragile. Edits outside the markers are
  lost, and the markers constrain how people write code.
- **Never touch edited files**: safe, but the project drifts away from the specification.
- **Three-way merge** (how Git and Copier-style template upgraders work): needs the
  original generated version as the common base.

## Decision

- **The base is reproduced, not stored.** Generation is deterministic (ADR-0014), so the
  manifest in the user's copy (spec revision and generator version) is enough to regenerate
  the exact project they started from. When the generator version differs, the base cannot
  be reproduced. The manifest's SHA-256 hashes still identify untouched files, which are
  upgraded. Edited files are kept, and the new version is written next to them as
  `<path>.regenerated`.
- **Line-based three-way merge** (`codegen_react.merge`, standard library only):
  - A change made on only one side is taken as it is.
  - Identical changes on both sides are taken once.
  - Changes that overlap, or merely touch, become a conflict with Git-style markers
    (`<<<<<<< your edit` … `>>>>>>> regenerated rN`). Adjacent edits are treated as
    conflicts on purpose, so nothing is silently guessed.
- **Every file gets an explicit outcome:** `unchanged`, `regenerated`, `kept`, `merged`,
  `conflict`, `added`, `user-file`, `removed`, `orphaned`, `deleted`, `restored` or
  `side-by-side`. Files the user added, including binary ones, are carried over unchanged.
  The manifest always takes the new version, so the next upgrade has the right base.
- **API:** `POST /projects/{id}/code/upgrade?to=` takes the edited zip as
  `application/zip` and returns the outcomes plus the upgraded zip. The upload is read with
  the build runner's bounded, traversal-safe reader (ADR-0015); it is never executed or
  stored. Each upgrade is audited.
- File headers now say the file may be edited (generator 0.5.0).

## Consequences

- Hand edits survive regeneration. When they collide with generated changes, they are
  marked rather than lost.
  - **Tests:** unit tests over every outcome; API tests with a real spec change, covering a
    clean merge, a conflict and a generator mismatch.
  - **Fuzzing:** 3,000 randomized merges were run during development. Edits separated by at
    least one unchanged line always merged to the expected text, and no user line was lost.
- The merge is line-based, not syntax-aware. A clean textual merge can still produce code
  that does not compile, for example a renamed identifier used in the user's code. The
  isolated build (ADR-0015) is the check for that.
- Upgrading across generator versions degrades to side-by-side files. Keeping old
  generator versions runnable, so their output can be reproduced, is a possible follow-up.
