# ADR-0009: Two-stage skill routing, evaluated against a lexical baseline

- Status: Accepted · Date: 2026-10-04

## Context

With more than one skill, the workspace must decide which skill handles a request. The
brief requires metadata filtering before any model-based selection, forbids using an LLM
for deterministic lookups, says keyword matching must not be the sole routing mechanism,
and requires the router to be evaluated on a labeled set against a simple baseline.

## Decision

1. **Stage 1 — deterministic filter.** Keep the latest version of every skill whose
   manifest preconditions the specification satisfies (for example `acceptance-criteria`
   needs `/functional_requirements`). No model call.
2. **Stage 2 — choose.**
   - A skill the person picked explicitly is validated against stage 1 (422
     `skill-not-applicable` with the unmet preconditions) and used.
   - Zero candidates → no skill. One candidate → that skill, without a model call.
   - Several candidates → the model chooses one, or `none`, through a schema whose
     `skill_id` is a `Literal` of the candidate ids. Invented ids fail validation and get
     the single repair attempt; persistent failure fails the run.
3. **No silent fallback.** If model routing fails, the run fails with the classified error.
   The keyword scorer is never substituted for the model at runtime.
4. **Routing is part of the run.** Runs start with an optional `skill_id`; routing happens in
   the background executor with its own budget (2 calls, 8k tokens, 60 s) and is recorded in
   `workflow_runs.routing` (method, candidates, choice, confidence, rationale, model
   telemetry). The generic `/projects/{id}/runs` resource replaces `/discovery-runs`
   (API v1 is unreleased; the only client is the workspace UI, updated in the same change).
5. **Evaluation.** `evals/datasets/routing/v1.jsonl` (30 labeled cases: three skills and
   out-of-scope requests) is scored with the same stage 1 for both methods:
   - `lexical` — deterministic keyword-overlap baseline, run in CI on every change and
     published as a PR notice. Baseline at introduction: 63% accuracy (19/30), 33% false
     invocations, 33% missed invocations.
   - `router` — the production router; requires a configured model, run opt-in.
   No accuracy threshold is enforced until real-model baselines exist; thresholds will be
   set from those measurements.

## Consequences

- Routing costs nothing while only one skill applies (every new project) and one small
  model call otherwise.
- The baseline makes model routing's value measurable instead of assumed; the dataset is
  versioned and must not be tuned to either method.
- Adding a skill requires adding labeled routing cases for it.
- Routing plus one skill call is still a two-step, linear flow, so no graph runtime is adopted
  here (ADR-0008 §6). Checkpointed, multi-step orchestration is evaluated in Milestone 2c.
