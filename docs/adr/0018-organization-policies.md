# ADR-0018: Organization policies as typed, deterministic rules

- Status: Accepted · Date: 2026-10-10

## Context

Organizations need guardrails that apply to every project. Examples: "no file uploads",
"Angular only", "forms stay small", "sensitive fields require a confidential classification"
and "requirements need acceptance criteria before code is generated". The guardrails must be
explainable, enforceable and auditable. They must not depend on model output, and the
workspace must not execute anything an organization uploads.

## Decision

- **Typed rules, fixed kinds** (`packages/org-policy`):
  - A policy set is versioned data: `policy_version: "1"`, at most 50 rules with unique ids.
  - Each rule is one of nine kinds, evaluated by deterministic code against the spec and
    the UI IR: allowed frameworks, allowed design systems, forbidden components, maximum
    form fields, acceptance criteria required, confirmed requirements only, sensitive fields
    need a classification, entity naming, and required screen states.
  - Unknown kinds or extra fields are rejected. The only organization-supplied expression is
    an entity-naming regex: at most 80 characters, compiled at validation, and matched
    against ids of at most 64 characters.
- **Severity:** `error` findings block code generation, builds and upgrades for the
  affected revision (`422 policy-blocked`, with one entry per finding naming the rule).
  `warning` findings are reported. Earlier compliant revisions still generate. The impact
  preview reports policy findings before a change is saved.
- **Administration:**
  - One policy set per tenant (`org_settings`).
  - Changes need the `org-admin` role and `If-Match: "vN"`; concurrent edits get `412`.
  - Every change is audited with the rule ids.
  - Development auth reads roles from `X-Dev-Roles`; a production identity provider maps
    its groups onto the same role names.
- **UI:** an Organization page edits the policy as JSON, with server validation. The Code
  tab shows blocking findings through the standard problem display.

## Consequences

- Guardrails are explainable: every finding names its rule, a JSON path and a reason.
- Adding a rule kind is a code change with tests, not configuration. This is deliberate:
  it keeps evaluation safe and predictable.
- Policies apply to code generation, not to editing the spec, so teams can always work
  their way back into compliance.
