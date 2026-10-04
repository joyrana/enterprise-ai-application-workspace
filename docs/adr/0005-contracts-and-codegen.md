# ADR-0005: Generated, drift-checked API contracts

- Status: Accepted · Date: 2026-10-04

## Decision

- FastAPI generates the OpenAPI document from typed routes; the spec schema inside it is the
  same Pydantic model used for validation.
- `python -m workspace_api.export` writes `contracts/openapi.json` and
  `contracts/application-spec.schema.json`. Both are committed.
- `openapi-typescript` generates `apps/workspace-web/src/api/schema.d.ts` from the committed
  OpenAPI document. The web client derives all request/response types from it.
- CI regenerates all three and fails on any difference, so contract changes are explicit in
  review and the frontend cannot silently drift from the backend.
- Errors use RFC 9457 `application/problem+json` with a stable `type` URN, `request_id`,
  and field-level `errors[].path` in JSON-pointer form.

## Consequences

- One source of truth for types across Python and TypeScript.
- Contributors must run the export and `npm run gen:api` after API changes (or push a
  `[regen]` commit; see ADR-0006).
