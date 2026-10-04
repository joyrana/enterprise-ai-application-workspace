# ADR-0006: CI as the verification source; generated lockfiles

- Status: Accepted · Date: 2026-10-04

## Context

The initial implementation was authored where package registries were unreachable, so
dependencies could not be resolved or tested locally. The brief forbids claiming results
that were not observed and requires reproducible, locked dependencies.

## Decision

- GitHub Actions (`ci.yml`) is the authoritative verification for every change: format,
  lint, strict typing, tests against a real PostgreSQL 16 service, contract drift, build,
  dependency audit, secret scan and dependency review.
- `REQUIRE_DB=1` in CI turns "database not configured" from a skip into a failure, so
  integration tests cannot silently disappear.
- `uv.lock` and `package-lock.json` are committed and installs are `--locked` / `npm ci`.
- `regenerate.yml` is an opt-in workflow for feature branches: a commit message containing
  `[regen]` makes CI resolve dependencies, regenerate contracts and commit them back.
  It needs `contents: write` and never runs on `main` or for forks.
- Third-party actions are pinned to full commit SHAs with the release tag in a comment.
  Workflows default to `contents: read`; checkout does not persist credentials.

## Consequences

- Reported results always link to a CI run.
- A bot commit does not trigger CI by itself (GitHub's GITHUB_TOKEN rule); the next push
  does. Reviewers see lockfile changes as ordinary diffs.
