# ADR-0001: Modular monolith with explicit package boundaries

- Status: Accepted · Date: 2026-10-04

## Context

The brief asks for clear boundaries between UI, orchestration, domain logic, design systems,
generation and validation, while warning against microservices "for architectural
appearance". The team is small and the product is pre-MVP.

## Decision

- One deployable Python API (`services/api`) plus a separately built web app
  (`apps/workspace-web`).
- Domain contracts live in libraries with no web or database dependencies
  (`packages/application-spec` depends only on Pydantic). Later packages (skill SDK, UI IR,
  design-system adapters) follow the same rule.
- The API layers are: routes (transport only) → service (use cases, tenancy, transactions)
  → db (persistence). Business rules never live in route handlers or React components.
- A uv workspace ties Python packages together; each has its own `pyproject.toml`.
- The isolated build runner (Milestone 4) is the first planned separate process, because
  untrusted generated code must not run in the API process. That is a security boundary,
  not a scaling decision.

## Consequences

- Simple local development and deployment; one database transaction can cover a revision
  and its audit event.
- Boundaries are enforced by package dependencies and review rather than the network, so
  discipline matters: libraries must not import from services.
