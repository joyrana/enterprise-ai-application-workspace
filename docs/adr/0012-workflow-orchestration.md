# ADR-0012: Checkpointed workflows on our own tables; LangGraph not adopted yet

- Status: Accepted · Date: 2026-10-04

## Context

Until now every AI run was one routed skill call. The next capability is a **multi-step
workflow**, for example discovery → acceptance criteria → conflict check. Each step proposes
changes, a person reviews them, and the next step must build on what the person accepted.
Requirements from the brief and earlier ADRs:

- **Durable and resumable.** A crash, deploy or stale run must never lose progress or redo an
  applied step. A person must be able to resume a failed step, a bounded number of times.
- **Human gates are first-class.** A step's proposals are applied only by a person
  (ADR-0008), with `If-Match` on the spec revision (ADR-0003). The next step starts from the
  revision the person produced.
- **Auditable and tenant-scoped**, like every other state change. No unrestricted tools.
- **Deterministic control flow.** Which step runs next is decided by code, not by a model.

### Options

**A. LangGraph.** Checked against upstream `pyproject.toml` files on 2026-10-04:
`langgraph` 1.2.11 (MIT) and `langgraph-checkpoint-postgres` 3.1.2 (MIT). It offers graph
state, checkpointers (including PostgreSQL), and `interrupt()` for human-in-the-loop pauses.
What it would cost here:

- New runtime dependencies: `langchain-core`, `langgraph-sdk`, `langgraph-prebuilt`,
  `langgraph-checkpoint`, plus `psycopg-pool` and `orjson` for the Postgres checkpointer.
  That is a large surface to audit for a three-step linear flow.
- A second persistence model. Checkpoints live in LangGraph's own tables and serialization
  format, outside our migrations, tenancy filters, audit trail and immutable-revision rules.
  The human decision would then exist twice: as our `apply` (with `If-Match` and audit) and as
  a graph resume.
- Its strengths are cycles, tool-calling agent loops, parallel branches and streaming.
  We need none of these yet: our steps are sequential, and each is a bounded skill call.

**B. Our own checkpointed state machine on existing PostgreSQL tables** (chosen). A pure,
typed transition function (`skill_sdk.workflow`). The state is a JSONB checkpoint on a
`workflows` row, and each step execution is an ordinary `workflow_runs` row.

**C. A general workflow engine** (Temporal or similar). Strong durability guarantees, but it
means new infrastructure to operate. That is premature for one API service.

## Decision

- `skill_sdk.workflow` defines workflows as ordered steps with deterministic transitions:
  `pending → running → awaiting_review → completed`, or `skipped` (preconditions unmet)
  or `failed`. The workflow status is `running | awaiting_review | completed | failed |
  cancelled`. The functions are pure and are unit-tested without a database.
- **The checkpoint is written in the same transaction as the event that causes it.** A step
  run finishing, its proposals being applied, a resume and a cancel each write the run and
  the workflow state in one transaction. No in-memory progress exists to lose.
- **Gates reuse the run review.** A step with proposals waits for `apply`. Applying, even
  with every proposal rejected, completes the step and starts the next one against the new
  current revision.
- **Recovery.** If a step run is left unfinished (process stopped), the existing stale-run
  expiry marks it `interrupted`. Reading the workflow reconciles the step to `failed`, and
  **Resume** retries it. A step may run at most `max_attempts_per_step` times (default 2).
  Resume also restarts a stalled workflow whose next step has no run.
- Every transition is audited (`workflow.*`). Workflows are tenant-scoped like projects.

## Revisit LangGraph when

Any of these becomes a real requirement: model-directed branching or loops (an agent
choosing tools); parallel fan-out and join across steps; streaming intermediate step output;
or workflows defined by users rather than by code. Any adoption would have to keep our
`apply` as the only way a spec changes, and store checkpoints under our tenancy and audit
rules.

## Consequences

- No new dependencies. The workflow state is visible in the same database, API and audit
  trail as everything else.
- We own the engine. It is small (sequential steps only), and its transition function is
  covered by unit tests plus API tests for gates, skips, failures, interruption and resume.
- Parallel steps, timers and long waits for external events are not supported. Adding them
  is the trigger to revisit this ADR rather than to grow the engine.
