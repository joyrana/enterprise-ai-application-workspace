# ADR-0010: Evidence tiers — what each kind of test may claim

- Status: Accepted · Date: 2026-10-04

## Context

The brief forbids fabricated results and overstated readiness. The workspace now has four
kinds of evidence with very different meanings, and reports must never blur them.

## Decision

| Tier | Where | What it proves | What it does **not** prove |
|---|---|---|---|
| 1. Unit and component tests | `pytest`, Vitest (jsdom), every PR | Contracts, invariants, error handling, UI states | Browser behaviour, accessibility, model quality |
| 2. Integration with a fake provider | API tests against PostgreSQL, every PR | Runs, routing, apply semantics, tenancy, concurrency over real HTTP and DB | Anything about real model output |
| 3. End-to-end in a real browser | Playwright + axe, `e2e` CI job, every PR; model replaced by a scripted OpenAI-compatible server | The full browser → API → DB → HTTP-provider path; WCAG 2.1 A/AA checks (serious/critical) on key views | Model quality; manual screen-reader experience |
| 4. Real-model evaluation | `real-model-eval.yml` (opt-in), or locally with any configured model | Measured routing and discovery quality for **the named model, version, hardware and dataset** | Other models, other hardware, production load |

Rules:

1. Every reported number names its tier and, for tier 4, the model tag and digest, runtime
   version, hardware class, temperature/seed, dataset version and commit.
2. Tier-4 results from a small CPU model are a floor, not a forecast for production models.
3. Deterministic baselines (the lexical router) may be reported as real measurements because
   they are reproducible bit-for-bit.
4. axe exclusions are allowed only for library internals, named and justified in the test
   (currently Fluent's `data-tabster-dummy` focus sentinels).
5. Quality thresholds are enforced in CI only for tier 1–3 and for deterministic baselines;
   tier-4 thresholds are set once at least two models have baselines.

## Consequences

- The E2E tier already paid for itself: it found two defects tiers 1–2 could not see — the
  app root left `aria-hidden` after creating a project, and untouched AI proposals being sent
  as *rejected* when proposals arrived after a run started.
- Real-model numbers are cheap to refresh (one workflow dispatch) and always attributable.
