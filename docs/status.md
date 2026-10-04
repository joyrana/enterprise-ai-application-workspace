# Implementation status

Last updated: 2026-10-04 · Milestone 2a (PR #2)

## Milestone 2a — AI discovery with human review

Evidence: GitHub Actions run
[37204402670](https://github.com/joyrana/enterprise-ai-application-workspace/actions/runs/37204402670)
on PR #2. Test counts are taken from the runners' own summary lines, which CI publishes as
PR notices.

| Check | Result |
|---|---|
| Python: ruff, mypy `--strict` (all six Python packages) | Pass |
| Python: pytest, **202 passed** (spec, model gateway incl. httpx transport tests, skill SDK, business-discovery skill, eval harness, API incl. discovery runs against PostgreSQL 16, migrations 0001→0002 round-trip) | Pass |
| Generated contracts (OpenAPI, JSON Schema) and TypeScript API types match code | Pass |
| pip-audit, npm audit, gitleaks | Pass |
| Web: Prettier, ESLint + jsx-a11y, `tsc` strict, Vitest **28 passed** (6 files), production build | Pass |
| Dependency review | Not run: "Dependency graph" is disabled in repository settings |

### What these results do and do not show

- They show the gateway, skill, API and UI behave as specified **with a fake provider**:
  validation and repair, retries, error classification, budgets, the data-classification
  gate, prompt-injection framing, proposal conversion, decision application invariants,
  idempotency, tenancy and conflict handling.
- They do **not** show anything about Qwen or gpt-oss quality. No real model has been run
  from this environment. Real results come from
  `uv run python -m workspace_evals.discovery --repeats 3` with a configured model, and will
  be recorded here with the model, dataset version and commit when run.

### Milestone 2a checklist

- [x] Model gateway per ADR-0007: hf-router (Qwen), self-hosted, ollama (gpt-oss) profiles
- [x] Structured output: reasoning/harmony stripping, JSON extraction, validation, one repair
- [x] Bounded retries with backoff and Retry-After; classified errors; per-run budgets
- [x] Data-classification gate for remote providers; secrets redacted; no prompt text in telemetry
- [x] Skill SDK: manifests, versioned registry, metadata/precondition filtering
- [x] Typed spec commands with safe apply (ADR-0008)
- [x] business-discovery skill with versioned prompt
- [x] Durable runs with background execution, idempotent start, interrupted-run recovery, per-tenant limit
- [x] Discovery tab: start, poll/resume, per-proposal accept/confirm/reject, conflict handling
- [x] Discovery eval dataset v1 and runner (JSON + Markdown reports)
- [ ] Baseline real-model eval results for Qwen and gpt-oss (needs a configured model)

### Known limitations (2a)

- In-process executor: durable but single-process; a restart interrupts running calls
  (marked `interrupted`, user starts a new run). Checkpointed orchestration is planned for 2b.
- One skill only; no intent routing yet, so the routing eval suite does not exist yet.
- Projects with *unknown* data classification may use a remote model.
- Proposals cannot be edited before accepting; edit afterwards in the Specification tab.
- Starlette reports that `httpx` in its TestClient is deprecated in favour of `httpx2`;
  harmless now, to be addressed when upgrading test dependencies.

### Next slice: Milestone 2b

1. Baseline eval runs for gpt-oss (Ollama) and Qwen (HF router), recorded with model and commit.
2. Additional discovery skills (persona-discovery, requirements-elicitation, acceptance-criteria,
   requirements-conflict-detection).
3. Two-stage intent routing (metadata filter + model selection among candidates) with a
   labeled routing dataset and a simple baseline for comparison.
4. Orchestration with checkpointing and resumption; ADR on whether LangGraph earns its place.
5. Playwright E2E smoke test with axe checks.

---

# Milestone 1 — Foundation

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

## Next slice at the time (superseded by Milestone 2a above)

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
