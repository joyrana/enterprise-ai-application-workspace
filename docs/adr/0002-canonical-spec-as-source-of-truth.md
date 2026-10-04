# ADR-0002: Canonical specification as the single source of truth

- Status: Accepted · Date: 2026-10-04

## Context

Every later stage (discovery, UI planning, generation, validation) needs one authoritative,
machine-checkable description of the application. The brief requires distinguishing
user-provided facts, model proposals, derived information, approved decisions and
unresolved assumptions, and forbids filling unknowns with invented facts.

## Decision

- `appspec.ApplicationSpec` (schema `1.0.0`) is the canonical spec, defined in Pydantic v2
  with `extra="forbid"` everywhere.
- Scalar facts use `Tracked[T]` with `status ∈ {unknown, proposed, confirmed}`. Invariants:
  unknown ⇒ no value; proposed/confirmed ⇒ value + provenance; confirmed ⇒ `confirmed_by`.
- Collection items (`TrackedItem`) carry a stable kebab-case `id`, status
  (`proposed`/`confirmed`) and provenance. Genuinely unknown things are `open_questions`.
- `Provenance.source ∈ {user, model, derived, system}`; model-sourced values must name the
  skill and model, and may name skill and prompt versions.
- IDs share one namespace across sections, so cross-references are unambiguous.
- Structural validation (Pydantic) and semantic validation (`validate_spec`: dangling
  references → errors, completeness gaps → warnings) are separate; warnings never block
  saving.
- Revision metadata (`created_in`, `updated_in`) is stamped by the server only.
- The spec is framework-neutral. Rendering concerns go into the UI IR (Milestone 3).
- Schema evolution: bump `schema_version`, add a migration to `versioning._MIGRATIONS`;
  stored revisions are migrated on read, never rewritten.
- A JSON Schema (draft 2020-12) is exported for non-Python consumers and committed to
  `contracts/`.

## Consequences

- The spec can be validated, diffed and tested without an LLM.
- Being strict means early clients get rejections for typos instead of silent data loss.
- One shared ID namespace requires generators to choose distinct IDs (e.g. `role-…`).
