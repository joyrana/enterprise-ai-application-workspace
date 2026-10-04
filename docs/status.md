# Implementation status

Last updated: 2026-10-04 · Milestone 1 (PR #1)

## Verified results

Evidence: GitHub Actions run
[37191274574](https://github.com/joyrana/enterprise-ai-application-workspace/actions/runs/37191274574)
on PR #1.

| Check | Result |
|---|---|
| Python: ruff format + lint | Pass |
| Python: mypy `--strict` (application-spec, api) | Pass |
| Python: pytest, 83 tests: spec unit tests, API offline tests, PostgreSQL 16 integration tests, migration up/down/up + model-drift check, concurrent-save race | Pass (database tests forced on with `REQUIRE_DB=1`) |
| Generated contracts (OpenAPI, JSON Schema) match code | Pass |
| pip-audit (locked Python dependencies) | Pass |
| Web: generated API types match OpenAPI | Pass |
| Web: Prettier, ESLint (incl. jsx-a11y), `tsc` strict (app + Vite config) | Pass |
| Web: Vitest (client, projects page, project page, spec editor) | Pass |
| Web: production build | Pass |
| npm audit (runtime dependencies, high+) | Pass |
| gitleaks (full history) | Pass |
| Dependency review | **Not run**: needs "Dependency graph" enabled in repository settings |

Locked versions at this point include FastAPI 0.142.2, SQLAlchemy 2.0.54, Alembic 1.20.0,
Pydantic 2.13.5, React 18.3.1, Fluent UI React 9.74.9 and Vite 6.4.3.

## Milestone 1 checklist

- [x] Repository assessment, acceptance criteria, ADRs 0001–0007, threat model
- [x] Canonical application spec v1.0.0 with tracked status, provenance, validation, revision stamping, JSON Schema
- [x] PostgreSQL persistence with Alembic migrations; immutable revisions (DB trigger)
- [x] Project create/list/get; idempotent create; tenant isolation
- [x] Spec read/save/validate with ETag/If-Match; revision history; audit trail
- [x] RFC 9457 errors, request ids, body limit, security headers, redacted config
- [x] Workspace shell, projects, overview, spec editor, history, audit (Fluent UI v9)
- [x] OpenAPI-generated TypeScript client with drift checks
- [x] CI: lint, types, tests, build, contracts, audits, secret scan; failing steps annotate PRs
- [x] Seed data and local development instructions

Exit criterion "a user can create a project and persist a validated specification": met,
demonstrated by `test_create_project_*` and `test_save_creates_new_revision_and_syncs_project`
(API) and the `ProjectsPage` / `SpecEditorTab` tests (UI).

## Known limitations

- **Authentication is development-only** (trusted headers). Refused in production
  configuration; a real identity provider is required before any shared deployment.
- **The spec editor is raw JSON.** It is suitable for power users and for testing the
  contract. Structured section editors come with the Milestone 2 discovery skills.
- **No browser-level E2E or automated axe checks yet.** Component tests run in jsdom, which
  cannot emulate Fluent's layout-dependent focus management. One assertion (the page after
  closing the create-project dialog) therefore queries with `hidden: true`. Real-browser
  accessibility of dialog → navigation flows is to be covered by Playwright.
- **Revision history UI shows the latest 20 revisions.** The API paginates; the UI does
  not page further yet.
- **No real-browser manual smoke test has been recorded** for this milestone.
- Dependency review is inactive until Dependency graph is enabled.

## Next highest-priority slice: Milestone 2 (intent and skills)

1. Model provider abstraction per ADR-0007: one OpenAI-compatible adapter with `hf-router`
   (Qwen), `self-hosted` and `ollama` (gpt-oss) profiles; capability flags,
   validate-and-repair, usage accounting, error classification, a fake provider for tests.
2. Skill SDK and registry: typed contracts, metadata, preconditions, versioning.
3. First discovery skills (business-discovery, persona-discovery, requirements-elicitation,
   ambiguity-resolution) that emit *proposals* as typed spec commands, never raw mutations.
4. Orchestration with checkpointing and resumption (LangGraph, if evaluation confirms it
   earns its place), with budgets and deadlines.
5. Routing and requirements eval datasets, run against both Qwen and gpt-oss.
6. Playwright E2E smoke test covering create → save → history, including axe checks.
