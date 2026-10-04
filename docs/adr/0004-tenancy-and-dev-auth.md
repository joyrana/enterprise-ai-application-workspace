# ADR-0004: Tenant scoping and a replaceable authentication boundary

- Status: Accepted · Date: 2026-10-04

## Context

The platform is multi-tenant by design (organization design systems, policies), and the
brief lists cross-tenant access and unauthorized project access as threats. No identity
provider is chosen yet.

## Decision

- Every table that holds tenant data has `tenant_id`; every service query filters by the
  caller's tenant. A project in another tenant returns 404, identical to a missing one, so
  identifiers cannot be probed.
- Idempotency keys are unique per tenant, not globally.
- Route handlers depend only on a `Principal(tenant_id, user_id)`. Milestone 1 provides
  `AUTH_MODE=dev`, which reads `X-Dev-Tenant` / `X-Dev-User` with strict format validation.
- `AUTH_MODE=dev` is refused at startup when `APP_ENV=production`.
- Role-based authorization inside a tenant is deferred to the milestone that introduces
  approvals and organization policies; until then every authenticated tenant member can edit.

## Consequences

- Swapping in OIDC/JWT verification changes one module.
- The current build must not be exposed to untrusted users; this is stated in the README
  and the threat model.
- Row-level security in PostgreSQL is a candidate hardening step once tenancy rules settle.
