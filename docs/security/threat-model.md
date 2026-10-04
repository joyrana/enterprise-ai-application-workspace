# Threat model (Milestone 1 scope)

Date: 2026-10-04. Revisit at every milestone; Milestones 2 (model calls) and 4 (untrusted
code execution) add major new trust boundaries.

## Assets

- Project specifications (may contain confidential business processes and data models).
- Revision history and audit trail (integrity matters for accountability).
- Tenant isolation.
- Database credentials. Later: model-provider tokens (`HF_TOKEN`), generated source code.

## Trust boundaries

1. Browser ↔ API (untrusted client input; identity asserted by headers in dev mode).
2. API ↔ PostgreSQL (credentials via environment).
3. CI ↔ repository (workflow permissions, third-party actions).
4. *Future:* API ↔ model providers (prompts leave the network on the HF router); API ↔ build
   runner (untrusted generated code).

## Threats and mitigations

| Threat | Mitigation in place | Residual risk |
|---|---|---|
| Spoofed identity | Dev auth validates header format; refused when `APP_ENV=production` | **High if deployed** before a real IdP: anyone can claim any tenant. Do not expose this build to untrusted networks. |
| Cross-tenant access | Every query filters by tenant; foreign projects return 404; tests cover read and write paths | Missing filter in future code; consider PostgreSQL row-level security |
| Tampering with history | Append-only revisions; DB trigger rejects `UPDATE`; audit events per change | A DB superuser can still alter data; off-site backups and log shipping later |
| Lost updates / races | `If-Match` + row lock; concurrency test | — |
| Duplicate creation on retry | Idempotency keys scoped per tenant with body fingerprint | — |
| Oversized / malicious payloads | 1 MiB body limit (also for chunked bodies); strict schemas reject unknown fields; string length limits | Deeply nested JSON within the limit is bounded by schema shape but not by explicit depth limits |
| Injection | SQLAlchemy parameterized queries; no raw SQL with user input; no `dangerouslySetInnerHTML` (lint rule); React escapes output | — |
| Information leakage in errors/logs | RFC 9457 responses without stack traces; access logs record method, path, status, latency and request id only; settings repr redacts passwords | — |
| Clickjacking / MIME sniffing | `X-Frame-Options: DENY`, `nosniff`, `no-store`, `no-referrer` on all responses | A Content-Security-Policy for the web app is added with the production web deployment |
| CORS misuse | Off by default (dev proxy keeps same origin); explicit origins only; `*` refused | — |
| Secret leakage in the repo | `.env` git-ignored, placeholders only in `.env.example`, gitleaks scans full history in CI | — |
| Supply-chain attacks | Lockfiles, `npm ci` / `uv sync --locked`, pip-audit, npm audit, dependency review, SHA-pinned actions, checksum-verified gitleaks download | Compromised upstream release within allowed ranges before advisories exist |
| CI privilege abuse | `contents: read` by default; only `regenerate.yml` writes, only on non-main branches via `push` (not available to forks); no secrets used | — |
| Prompt injection, excessive model spend, untrusted code execution | Not applicable yet (no model calls, no code execution) | Addressed in Milestones 2 and 4 (see ADR-0007 for the provider design and data-classification gate) |

## Not claimed

Passing scans does not mean the system is secure. No penetration test or external review has
been done.
