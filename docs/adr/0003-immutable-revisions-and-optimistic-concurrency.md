# ADR-0003: Immutable spec revisions with optimistic concurrency

- Status: Accepted · Date: 2026-10-04

## Context

Users, and later AI skills, edit the same spec. The brief requires preserving
approved decisions, detecting stale state, recomputing only affected artifacts and keeping
an auditable history.

## Decision

- Every save appends a row to `spec_revisions` (whole document as JSONB, content hash,
  semantic hash, author, summary). Rows are never updated; a PostgreSQL trigger rejects
  `UPDATE` as defence in depth.
- `projects.current_revision` points at the latest revision.
- Writes require `If-Match: "r<N>"`. The service locks the project row (`SELECT … FOR
  UPDATE`), compares N with the current revision and fails with 412 on mismatch; missing
  If-Match fails with 428. Concurrent writers serialize on the lock, so only one wins.
- A save whose semantic content equals the current revision creates no new revision
  (`X-Revision-Created: false`).
- Element-level `created_in` / `updated_in` stamps are computed by diffing against the
  previous revision by element ID, so reordering is not a change. Later milestones use these
  stamps for dependency-aware recomputation.
- Whole-document storage is chosen over per-element tables for Milestone 1: specs are
  small (limited to 1 MiB requests) and whole-document revisions are trivially reproducible.

## Consequences

- Full history and cheap reproducibility; diffs are computed, not stored.
- Storage grows with every save; acceptable at current sizes and revisitable with
  retention policies (Milestone 7).
- Clients must handle 412; the web app explains the conflict and offers a reload.
