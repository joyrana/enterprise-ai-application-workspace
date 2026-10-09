# Enterprise AI Application Workspace

An agentic workspace that turns natural-language business requirements into well-specified,
designed, generated, tested and validated enterprise applications, while honoring an
organization's design system, engineering conventions, accessibility requirements and
security policies.

> **Status: Milestone 4 in progress (deterministic React + Fluent 2 code generation).**
> The pieces in place:
> - projects, the canonical specification, revision history, the audit trail and the workspace UI;
> - AI skills with routing and human review, and checkpointed multi-step workflows;
> - a Fluent 2 design preview;
> - a deterministic generator that turns each spec revision into a buildable React app.
>
> Generator 0.4.0 (edit, confirmed delete and an HTTP data store) is in review. The isolated
> on-demand build runner and edit preservation are not built yet; see the roadmap. The
> platform is not complete.
>
> **Development authentication only: do not expose this build to untrusted users.**

## Architecture at a glance

The trust boundaries are drawn as boxes:
- Model output and generated code cross them only as validated data.
- Nothing generated runs inside the workspace.

```mermaid
flowchart LR
  user(["Analyst / engineer"]) --> web

  subgraph browser["Browser"]
    web["workspace-web<br/>React 18 · Fluent UI v9<br/>OpenAPI-typed client"]
  end

  subgraph api["services/api · FastAPI modular monolith"]
    routes["Routes<br/>transport only · RFC 9457 errors"] --> svc["Services<br/>tenancy · transactions · audit"]
    svc --> spec["application-spec<br/>typed, versioned source of truth"]
    svc --> sdk["skill-sdk<br/>router · safety screen · workflow state machine"]
    sdk --> skills["skills/<br/>discovery · criteria · conflicts · screen design"]
    skills --> gw["model-gateway<br/>schema validation · budgets · no silent fallback"]
    svc --> ds["design-system<br/>UI IR v1 · validation · Fluent 2 contract"]
    ds --> cg["codegen-react<br/>allowlisted printer · manifest · zip"]
  end

  subgraph data["Data"]
    db[("PostgreSQL 16<br/>spec revisions · runs · workflows · audit")]
  end

  subgraph models["Model providers · untrusted output"]
    hf["Qwen<br/>HF Inference Providers / self-hosted"]
    ol["gpt-oss<br/>Ollama"]
  end

  subgraph ci["CI · the only place generated code runs"]
    build["Generated apps<br/>strict tsc · Vite build · Playwright + axe"]
  end

  web -- "/api/v1" --> routes
  svc --> db
  gw -- "OpenAI-compatible HTTP" --> hf
  gw --> ol
  cg -. "files + SHA-256 manifest<br/>download / diff" .-> web
  cg -. "example specs" .-> build
```

## What works today

- **Canonical application spec** (`packages/application-spec`): a versioned, strictly typed
  source of truth with explicit `unknown` / `proposed` / `confirmed` status, provenance
  (user, model, derived, system), referential validation, server-stamped artifact revisions,
  canonical hashing and an exported JSON Schema.
- **API** (`services/api`): create and list projects, read and save spec revisions with
  optimistic concurrency (`ETag` / `If-Match`), idempotent creation, per-tenant isolation,
  audit trail, RFC 9457 errors and an OpenAPI document.
- **Workspace web** (`apps/workspace-web`): React + Fluent UI v9 shell, projects list and
  creation, requirement-status overview, spec editor with validation and conflict handling,
  revision history and audit views.
- **AI discovery** (`packages/model-gateway`, `packages/skill-sdk`, `skills/`): describe an
  application in plain language; Qwen (Hugging Face or self-hosted) or gpt-oss (Ollama)
  proposes objective, domain, personas, requirements, assumptions and open questions; you
  accept, confirm or reject each proposal, and accepted ones become one new revision with
  model provenance. Confirmed facts are never overwritten by later runs.
- **More skills and routing**: `acceptance-criteria` (Given/When/Then for requirements
  without criteria) and `requirements-conflict-detection` (contradictions and duplicates
  raised as blocking questions), and `screen-design` (proposes the screens the spec still
  needs; accepted screens feed the design preview). Requests are routed by preconditions first; the model only
  chooses when several skills apply, and you can always pick a skill yourself (ADR-0009).
- **Code generation** (ADR-0014): each spec revision yields a complete, static
  Vite + React + TypeScript + Fluent 2 project:
  - screens, forms with validation, and navigation actions;
  - tables bound to typed entity stores, with Edit and a confirmed Delete (0.4.0, in review);
  - an OpenAPI contract for the backend. Setting `VITE_DATA_API_URL` switches the app from
    browser storage to that backend.

  Every file carries a provenance header, dependencies are pinned exactly, and a SHA-256
  manifest lists every file. In the Code tab you can browse the files, diff any two
  revisions and download a zip. CI builds example apps (including one running against a
  contract-following test server), drives create/edit/delete in Chromium and checks every
  route with axe. The workspace never runs generated code.
- **Screens and design systems** (ADR-0013): the spec's screens (or, when none exist, its data
  entities) are turned into a typed UI intermediate representation, checked for
  accessibility rules and references, and mapped to Fluent 2 components through a contract
  pinned to the installed Fluent version. The Screens tab previews them with real Fluent
  components; nothing is executed.
- **Multi-step workflows** (ADR-0012): the requirements pipeline runs discovery, then
  acceptance criteria, then a conflict check, pausing for your review after each step. Its
  progress is checkpointed in PostgreSQL, so a crash never loses or repeats an applied step.
  A failed step can be retried a bounded number of times.
- **Prompt-injection screening** (ADR-0011): instruction-like text in a request is flagged
  as you type, the model is warned, and proposals that repeat the flagged text are marked
  and start as *Reject*. It is advisory; the structural review controls remain the boundary.
- **Evaluation** (`evals/`): discovery scenarios with deterministic checks, and a labeled
  routing set scored for a lexical baseline (in CI) and for the model router (opt-in).
- **CI**: lint, format, strict typing, unit and PostgreSQL integration tests, contract drift
  checks, production build, dependency audit, secret scan.

## How it works

### From a sentence to a running app

Each arrow into the specification passes through a person's decision. Everything after the
spec is deterministic code, so the same revision always yields byte-identical output.

```mermaid
flowchart TD
  req["Plain-language request"] --> screen{"Injection screen<br/>injection-scan@1"}
  screen --> route{"Router<br/>preconditions first,<br/>model picks only among eligible skills"}
  route --> skill["Skill run<br/>budgeted model call → schema-validated JSON"]
  skill --> props["Typed proposals<br/>with provenance, flagged ones default to Reject"]
  props --> review{"Human review<br/>accept · confirm · reject"}
  review -- "accepted" --> rev[("New spec revision<br/>immutable · ETag / If-Match · audited")]
  review -- "rejected" --> drop["Discarded, recorded in audit"]
  rev --> ir["Derive UI IR v1<br/>screens or entity list/form screens"]
  ir --> val{"Validate IR<br/>a11y · references · ids"}
  val -- "errors" --> blocked["Generation refused<br/>issues shown with JSON paths"]
  val -- "ok" --> adapt["Fluent 2 adapter<br/>render tree from a pinned contract"]
  adapt --> preview["Screens tab<br/>allowlisting interpreter, no code executed"]
  adapt --> gen["codegen-react<br/>JSON-literal printing, component allowlist"]
  gen --> out["Project files · manifest · deterministic zip"]
  out --> diff["Diff vs. any earlier revision → review"]
  out --> ci["CI: tsc · build · browser tests · axe"]
```

### One AI step, end to end

```mermaid
sequenceDiagram
  autonumber
  actor U as User
  participant W as Workspace web
  participant A as API
  participant S as Skill SDK
  participant G as Model gateway
  participant M as Qwen / gpt-oss
  participant DB as PostgreSQL

  U->>W: Describe the need
  W->>A: POST /runs (Idempotency-Key)
  A->>S: screen text (advisory flags)
  A->>DB: run queued
  A-->>W: 202 Accepted
  S->>S: route: preconditions, then model choice among candidates
  S->>G: prompt with untrusted-content notice + JSON schema
  G->>M: chat completion (bounded tokens, calls, deadline)
  M-->>G: answer
  G->>G: extract and validate JSON, bounded retry on invalid output
  G-->>S: typed result or explicit failure
  S->>DB: proposals with model provenance (atomic claim, no double apply)
  W->>A: poll run
  A-->>W: proposals, echo flags
  U->>W: Accept / confirm / reject each
  W->>A: POST /runs/{id}/apply with decisions (If-Match)
  A->>DB: one new spec revision + audit event, in one transaction
```

### Checkpointed workflows

The requirements pipeline (discover → acceptance criteria → conflict check) is a pure state
machine whose state is stored in PostgreSQL in the same transaction as each step's result
(ADR-0012). A crash never loses or repeats an applied step.

```mermaid
stateDiagram-v2
  [*] --> running
  running --> awaiting_review: step proposed changes
  running --> running: step had nothing to propose, next step starts
  awaiting_review --> running: decisions applied, next step
  running --> failed: step failed
  failed --> running: resume (at most 2 attempts)
  awaiting_review --> completed: last step reviewed
  running --> completed: last step done
  running --> cancelled
  awaiting_review --> cancelled
  failed --> cancelled
  completed --> [*]
  cancelled --> [*]
```

### Inside a generated app

```mermaid
flowchart LR
  subgraph app["Generated app · Vite + React + Fluent 2"]
    routes["Router<br/>one route per screen"] --> list["List screens<br/>bound tables · Edit · Delete with dialog"]
    routes --> form["Form screens<br/>native constraints · Field errors · ?id= edits"]
    list --> hooks["useEntityList / useRecord"]
    form --> save["saveRecord / deleteRecord<br/>typed conversion"]
    hooks --> store{{"Store interface<br/>one per entity"}}
    save --> store
  end
  store -- "default" --> local[("localStorage<br/>memory fallback")]
  store -- "VITE_DATA_API_URL set" --> http["HTTP store"]
  http -- "GET · POST · PUT · DELETE" --> backend["Your backend<br/>implements api/openapi.json<br/>behind your own auth"]
```

## Engineering practices

| Practice | How it is applied here | Reference |
|---|---|---|
| Human in the loop for consequential changes | Model output is only ever a *proposal*; a person accepts it into a new spec revision. Confirmed facts are never overwritten by later runs | ADR-0008 |
| Deterministic code where it suffices | Routing preconditions, workflow control flow, UI derivation and code generation are plain code; models only fill typed proposals | ADR-0009, 0012, 0014 |
| Typed, versioned contracts | Spec schema, UI IR v1, the design-system contract and OpenAPI are exported, drift-checked in CI and turned into TypeScript types | ADR-0002, 0005, 0013 |
| Untrusted model output and retrieved text | JSON-schema validation, an injection screen with echo detection, an untrusted-content notice in prompts, and flagged proposals that default to Reject | ADR-0011 |
| Bounded cost and retries | Per-run budgets (calls, tokens, deadline), bounded repair retries, bounded workflow resume, no silent fallback between models | ADR-0007 |
| Untrusted generated code | Spec text is emitted only as escaped JSON literals; components and props are allowlisted; the API never builds or runs output; CI is the execution boundary | ADR-0014 |
| Reproducibility and provenance | Byte-identical output per revision, provenance headers, SHA-256 manifest, exact dependency pins equal to the lockfile | ADR-0014 |
| Accessibility by default | IR rules (one h1, heading order, labels), Fluent semantics, axe WCAG 2.1 AA checks in CI on the workspace and on generated apps | ADR-0013, 0014 |
| Data integrity | Optimistic concurrency (`ETag` / `If-Match`), idempotent creation, tenant scoping, audit trail, immutable revisions | ADR-0003, 0004 |
| Measured, not asserted | Evaluation sets for discovery, routing and injection; results are recorded with their exact conditions in [docs/status.md](docs/status.md), by evidence tier | ADR-0010 |
| Supply chain | Locked dependencies, SHA-pinned GitHub Actions, dependency audit, secret scan; secrets never in prompts, code or bundles | ADR-0006 |

Known gaps:
- development authentication only;
- no isolated on-demand build runner;
- no edit preservation across regeneration;
- generated apps leave backend authentication to the deploying organisation.

The [threat model](docs/security/threat-model.md) tracks these.

## Quick start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22, Docker.

```bash
cp .env.example .env            # placeholders; adjust if needed
docker compose up -d postgres   # local database on 127.0.0.1:5432

uv sync
set -a; . ./.env; set +a
(cd services/api && uv run alembic upgrade head)
uv run python -m workspace_api.seed        # optional demo project (tenant "demo")
uv run uvicorn workspace_api.main:app --reload --port 8000
```

In a second terminal:

```bash
cd apps/workspace-web
npm ci
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

API docs: http://localhost:8000/docs

## Tests

```bash
uv run pytest                                        # DB tests skip unless DATABASE_URL is set
REQUIRE_DB=1 DATABASE_URL=postgresql+psycopg://workspace:change-me@localhost:5432/workspace uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy packages/application-spec/src services/api/src

cd apps/workspace-web && npm run lint && npm run typecheck && npm test && npm run build
```

Integration tests create and drop a temporary database per run, so they need a role that may
create databases (the docker-compose user can).

After changing API routes or the spec schema, regenerate contracts:

```bash
uv run python -m workspace_api.export --out contracts
(cd apps/workspace-web && npm run gen:api)
```

## Repository layout

```
apps/workspace-web/          React + Fluent UI v9 workspace
services/api/                FastAPI service, Alembic migrations, tests
packages/application-spec/   Canonical spec library (no web/DB dependencies)
packages/model-gateway/      Model providers (HF router, self-hosted, Ollama), validation, budgets
packages/skill-sdk/          Skill manifests, registry, commands, router, safety, workflows
packages/design-system/      UI IR, design-system contracts, Fluent 2 adapter
packages/codegen-react/      Deterministic React + Fluent 2 code generator
skills/                      Built-in skills (discovery, acceptance criteria, conflict check, screen design)
evals/                       Evaluation datasets and runners
contracts/                   Generated OpenAPI + JSON Schema (drift-checked in CI)
scripts/                     CI helpers and end-to-end test servers (fake model, fake data API)
docs/                        Assessment, architecture, ADRs, threat model
.github/workflows/           CI and lockfile regeneration
```

## AI models

Discovery works with **Qwen** (Hugging Face Inference Providers or self-hosted weights) and
**gpt-oss on Ollama** through one OpenAI-compatible adapter. Model output is always
validated, there is no silent fallback between models, and confidential projects are kept
off remote providers. See [ADR-0007](docs/adr/0007-model-providers.md) and
[ADR-0008](docs/adr/0008-proposals-decisions-and-runs.md).

Local quick start with gpt-oss:

```bash
ollama pull gpt-oss:20b
export MODEL_PROFILE=ollama MODEL_ID=gpt-oss:20b
uv run uvicorn workspace_api.main:app --reload --port 8000   # then open a project → Discovery
```

Evaluate the configured model (writes JSON and Markdown reports):

```bash
uv run python -m workspace_evals.discovery --repeats 3 --out reports/evals
uv run python -m workspace_evals.routing --method router --repeats 3 --out reports/evals
uv run python -m workspace_evals.routing --method lexical   # baseline, no model needed
uv run python -m workspace_evals.injection                  # detector precision/recall, no model needed
```

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 0 | Repository assessment, plan, ADRs | Done ([assessment](docs/assessment/milestone-0.md)) |
| 1 | Foundation: spec, persistence, API, workspace shell, CI | Done |
| 2a | Model gateway (Qwen / gpt-oss), skill SDK, business discovery with human review, discovery evals | Done |
| 2b | Acceptance-criteria and conflict-detection skills, two-stage routing, routing evals | Done |
| 2c | Real-model evaluation (Ollama + Qwen in CI), Playwright E2E with axe | Done |
| 2d | Prompt-injection hardening, checkpointed workflows, eval diagnostics and variance | Done (HF-router and gpt-oss baselines need a token / local run) |
| 3 | Design-system contracts, Fluent 2 adapter, UI intermediate representation | Done (entity/navigation proposals open) |
| 4 | React generation, isolated builds, preview, diff review | In progress (generation, diff, CI builds and CRUD done; isolated runner open) |
| 5 | Incremental changes, edit preservation, resilience | Planned |
| 6 | Angular + Material 3 | Planned |
| 7 | Organization design systems and policies | Planned |
| 8 | Research-grade evaluation | Planned |

## Real-model evaluation

`Actions → Real-model evaluation (Ollama) → Run workflow` evaluates routing and discovery
against an open-weight model served by Ollama on the CI runner (default `qwen3:4b-instruct`,
CPU only, no secrets). Latest results and their exact conditions are in
[docs/status.md](docs/status.md). End-to-end browser tests with axe accessibility checks run on
every PR (`cd apps/workspace-web && npm run e2e` locally, with the API and
`scripts/e2e/fake_openai_server.py` running).

## Documentation

- [Implementation status, verified results and known limitations](docs/status.md)
- [Milestone 0 assessment and acceptance criteria](docs/assessment/milestone-0.md)
- [Architecture overview](docs/architecture/overview.md)
- [Architecture decision records](docs/adr/README.md)
- [Threat model](docs/security/threat-model.md)
