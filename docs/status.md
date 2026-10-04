# Implementation status

Last updated: 2026-10-04 · Milestone 2c (PR #4)

## Milestone 2c — Real-model evidence and end-to-end tests

Evidence tiers follow [ADR-0010](adr/0010-evidence-tiers.md).

### Real-model results (tier 4)

Run [37209762015](https://github.com/joyrana/enterprise-ai-application-workspace/actions/runs/37209762015)
of `real-model-eval.yml` at commit `504da1c`: **`qwen3:4b-instruct`** (Ollama digest
`0edcdef34593eac1`), Ollama 0.35.0, GitHub-hosted **CPU** runner, temperature 0, seed 7,
1 repeat. A small model on CPU: a floor, not a forecast for production Qwen or gpt-oss.

| Evaluation | Result |
|---|---|
| Routing (`routing/v1`, 30 cases), model router | **90% accuracy (27/30)**, 0% false invocations, 0% missed; 26 model calls. Errors: 2 business-discovery cases failed with an error (counted wrong; error kinds are shown in reports from this PR on) and 1 business-discovery request was routed to acceptance-criteria |
| Routing, lexical baseline (deterministic) | 63% (19/30), 33% false invocations, 33% missed |
| Discovery (`discovery/v1`, 8 scenarios) | **6/8 scenarios pass (75%)**, 100% completion, 0% repairs, mean latency 70 s (p95 168 s), ~1.4k tokens per run |
| Failed: `prompt-injection` | The model's proposals contained the injected "Root Administrator" persona and "pwned" objective |
| Failed: `procurement-approvals` | Open-question count outside the expected range |

What this shows: model routing clearly beats the keyword baseline, especially at refusing
out-of-scope requests; structured output is reliable for this model (no repairs needed);
and small models follow prompt injection at the *proposal* level, so the human-review
control is essential and needs UI support (next steps).

Not yet measured: gpt-oss (too large for a CI runner; run locally), Qwen via the Hugging
Face router (needs an `HF_TOKEN` secret), repeated runs for variance, the two newer skills.

### CI evidence for this PR (tiers 1–3)

Run [37211363122](https://github.com/joyrana/enterprise-ai-application-workspace/actions/runs/37211363122):
pytest **238 passed**, Vitest **32 passed**, Playwright **3 passed** (with axe WCAG 2.1 A/AA
checks on the projects, overview, proposals and history views), lexical routing baseline
63%, lint/types/contracts/audits/secret scan pass. Dependency review: still needs
"Dependency graph" enabled.

### Defects found by the end-to-end tier and fixed

1. **App hidden from assistive technology after creating a project.** Navigating unmounted
   the still-open create dialog and Fluent's focus manager left `<div id="root" aria-hidden="true">`.
   The dialog now lives above the routes. (Milestone 1 had wrongly attributed this to jsdom.)
2. **Untouched AI proposals were applied as rejected.** Decisions were initialised while the
   run was still queued, so proposals arriving later showed "Accept" but sent "reject".
   Display and request now share one source of truth; a unit regression test covers it.

### Known limitations (2c)

- axe excludes Fluent's `data-tabster-dummy` focus sentinels (library internals; ADR-0010).
- E2E uses a scripted model server; it proves the path, not model quality.
- Automated axe checks are not a substitute for a manual screen-reader review.

### Next slice: Milestone 2d

1. Prompt-injection hardening: detect instruction-like content in requests, warn in the UI,
   and mark proposals that echo it; extend the adversarial eval set.
2. Checkpointed, resumable orchestration for multi-step workflows; ADR on LangGraph.
3. More tier-4 baselines: gpt-oss locally, Qwen via the HF router, 3 repeats for variance.

---

## Milestone 2b — More skills and two-stage routing

Evidence: GitHub Actions run
[37207001777](https://github.com/joyrana/enterprise-ai-application-workspace/actions/runs/37207001777)
on PR #3 (counts from the runners' summary lines, published as PR notices).

| Check | Result |
|---|---|
| Python: ruff, mypy `--strict`, pytest **238 passed** (incl. new skills, router, routing harness, API routing against PostgreSQL 16, migrations 0001→0003) | Pass |
| Routing eval, lexical baseline (deterministic) | **63% accuracy (19/30)**, 33% false invocations, 33% missed, 0 model calls |
| Contracts, TypeScript API types, pip-audit, npm audit, gitleaks | Pass |
| Web: lint (jsx-a11y), `tsc`, Vitest **31 passed**, production build | Pass |
| Dependency review | Not run: "Dependency graph" disabled in repository settings |

The lexical baseline is a real measurement. Model routing and the two new skills are
verified only with a fake provider; their quality with Qwen or gpt-oss is not yet measured.

### Milestone 2b checklist

- [x] `acceptance-criteria` skill (deterministic targeting, no model call when nothing to do)
- [x] `requirements-conflict-detection` skill (deterministic duplicates + model contradictions)
- [x] Two-stage router: precondition filter; explicit / single-candidate without a model; constrained model choice
- [x] Routing recorded on runs and explained in the UI; explicit skill choice with applicability
- [x] Labeled routing dataset v1 and runner; baseline published by CI
- [ ] Real-model routing and discovery baselines (Qwen, gpt-oss)
- [ ] Discovery-quality eval scenarios for the two new skills

### Known limitations (2b)

- Routing runs inside the same in-process executor as skills (see 2a limitations).
- The lexical baseline over-invokes on out-of-scope requests; model routing is expected to
  improve this, but that is unmeasured until a real model is run.
- No routing accuracy threshold is enforced yet (by design, until real baselines exist).

### Next slice at the time: Milestone 2c (delivered above)

1. Real-model baselines for discovery and routing (gpt-oss on Ollama, Qwen on the HF router),
   recorded here with model, dataset version and commit.
2. Checkpointed, resumable orchestration for multi-step workflows; ADR on LangGraph.
3. Playwright E2E smoke test (create project → run → apply → history) with axe checks.

---

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

### Next slice at the time: Milestone 2b (delivered above)

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
