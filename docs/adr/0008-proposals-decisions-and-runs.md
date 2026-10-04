# ADR-0008: Skills return typed proposals; people decide; runs are durable records

- Status: Accepted · Date: 2026-10-04

## Context

The brief requires that model output never mutates application state directly, that the
backend validates every action, that user-confirmed decisions are preserved, and that
proposals, user facts, derived data and approvals stay distinguishable. Model calls are
slow (seconds to minutes on local hardware) and can fail in many ways.

## Decision

1. **Skills return proposals, not edits.** A skill returns typed `SpecCommand`s
   (`set_fact`, `add_item`, `add_open_question`) with stable proposal ids. The model never
   produces commands or identifiers itself: it answers a small, model-friendly schema, and
   deterministic code converts that answer into commands, allocates collision-free ids,
   resolves references, removes anything already settled and caps list sizes.
2. **People decide per proposal.** For each proposal the person chooses *accept* (added
   as `proposed`), *confirm* (added as `confirmed`, `confirmed_by` = that person) or
   *reject*. A skill cannot set status, provenance or `confirmed_by`.
3. **Deterministic apply with invariants** (`skill_sdk.apply_commands`):
   confirmed facts are never overwritten; existing ids are never replaced; commands that
   would introduce dangling references are refused; every outcome is reported. The result
   is written through the same `write_revision` path as manual saves (validation,
   revision stamping, audit).
4. **Runs are durable records** (`workflow_runs`): input, base revision, proposals, model
   telemetry (model id, prompt version, tokens, latency, call outcomes — never prompt or
   completion text), classified errors, decisions and the resulting revision. Decisions can
   be applied once per run. Starting a run is idempotent with `Idempotency-Key`.
5. **Execution** is a background task after the HTTP response, claimed atomically
   (`queued → running`). Budgets come from the skill manifest (calls, tokens, deadline).
   Runs that outlive their deadline (process restart) are marked `failed/interrupted`. At
   most three active runs per tenant bound cost and load.
6. **No orchestration framework yet.** With one skill, a graph runtime adds no value. The
   next slice introduces routing between several skills; LangGraph is adopted only if it
   earns its place there (checkpointing, interrupts), recorded in a new ADR.

## Consequences

- Model mistakes cost a review, not a corrupted spec; prompt injection cannot confirm
  anything or overwrite settled facts.
- Every AI-originated element is traceable to a skill version, prompt version and model.
- The in-process executor does not scale horizontally and cannot resume a run mid-call;
  acceptable for this slice and replaced by the orchestration milestone.
