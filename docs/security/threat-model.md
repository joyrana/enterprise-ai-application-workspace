# Threat model (Milestone 1 scope)

Date: 2026-10-04, updated for Milestone 2a (model calls). Milestone 4 (untrusted code
execution) adds the next major trust boundary.

## Assets

- Project specifications (may contain confidential business processes and data models).
- Revision history and audit trail (integrity matters for accountability).
- Tenant isolation.
- Database credentials and model-provider tokens (`HF_TOKEN` / `MODEL_API_KEY`). Later: generated source code.

## Trust boundaries

1. Browser ↔ API (untrusted client input; identity asserted by headers in dev mode).
2. API ↔ PostgreSQL (credentials via environment).
3. CI ↔ repository (workflow permissions, third-party actions).
4. API ↔ model provider. With the Hugging Face router, prompts leave the network and reach
   third-party inference providers; with Ollama or self-hosted models they do not.
5. Model output → workspace (untrusted text that must never act as instructions or state).
6. *Future:* API ↔ build runner (untrusted generated code).

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
| Prompt injection via descriptions | User text is delimited as data (closing delimiter neutralised); the prompt forbids following embedded instructions; the model answers a narrow schema, deterministic code builds commands; skills cannot set status, provenance or `confirmed_by`; every proposal needs a human decision; confirmed facts are never overwritten (ADR-0008) | The model can still produce misleading *proposals*; review is the control. Adversarial eval scenario included |
| Malformed or hostile model output | Strict extraction (first complete JSON object), Pydantic validation, one repair attempt, list caps, classified `schema_failure` | — |
| Sensitive data sent to third parties | Data-classification gate refuses remote models for `confidential`/`restricted` projects unless an operator opts in; UI labels remote providers; audit records model and description length, not the text | Projects with *unknown* classification may use a remote model |
| Model credential leakage | Tokens read from the environment only, sent only as the `Authorization` header, redacted from `repr`; provider error bodies are never echoed to clients or logs | — |
| Excessive model spend / denial of service | Per-run budgets (calls, tokens, deadline) from the skill manifest; bounded retries with backoff; max 3 active runs per tenant; 8 000-character description limit | No per-tenant daily quota yet |
| Duplicate or replayed AI actions | Idempotent run creation; atomic `queued → running` claim; decisions applicable once per run; `If-Match` on apply | — |
| Untrusted code execution | Not applicable yet (no code generation) | Milestone 4 |

## Not claimed

Passing scans does not mean the system is secure. No penetration test or external review has
been done.
