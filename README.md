# Enterprise AI Application Workspace

An agentic workspace that turns natural-language business requirements into well-specified,
designed, generated, tested and validated enterprise applications, while honoring an
organization's design system, engineering conventions, accessibility requirements and
security policies.

> **Status: Milestone 2a (AI discovery).** Projects, the canonical specification, revision
> history, audit trail and the workspace UI exist, plus AI-assisted business discovery with
> human review. Skill routing, orchestration, design-system adapters and code generation are
> **not implemented yet**; see the roadmap below.
> Development authentication only: do not expose this build to untrusted users.

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
- **Evaluation** (`evals/`): a versioned discovery dataset with deterministic checks and a
  runner that reports completion, pass rate, repairs, latency and tokens for a real model.
- **CI**: lint, format, strict typing, unit and PostgreSQL integration tests, contract drift
  checks, production build, dependency audit, secret scan.

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
packages/skill-sdk/          Skill manifests, registry, typed spec commands
skills/                      Built-in skills (business-discovery)
evals/                       Evaluation datasets and runners
contracts/                   Generated OpenAPI + JSON Schema (drift-checked in CI)
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

Evaluate the configured model on the discovery dataset (writes JSON and Markdown reports):

```bash
uv run python -m workspace_evals.discovery --repeats 3 --out reports/evals
```

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| 0 | Repository assessment, plan, ADRs | Done ([assessment](docs/assessment/milestone-0.md)) |
| 1 | Foundation: spec, persistence, API, workspace shell, CI | Done |
| 2a | Model gateway (Qwen / gpt-oss), skill SDK, business discovery with human review, discovery evals | In review |
| 2b | More discovery skills, intent routing with labeled evals, orchestration with checkpointing | Next |
| 3 | Design-system contracts, Fluent 2 adapter, UI intermediate representation | Planned |
| 4 | React generation, isolated builds, preview, diff review | Planned |
| 5 | Incremental changes, edit preservation, resilience | Planned |
| 6 | Angular + Material 3 | Planned |
| 7 | Organization design systems and policies | Planned |
| 8 | Research-grade evaluation | Planned |

## Documentation

- [Implementation status, verified results and known limitations](docs/status.md)
- [Milestone 0 assessment and acceptance criteria](docs/assessment/milestone-0.md)
- [Architecture overview](docs/architecture/overview.md)
- [Architecture decision records](docs/adr/README.md)
- [Threat model](docs/security/threat-model.md)
