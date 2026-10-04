# ADR-0011: Prompt-injection screening is advisory and deterministic

- Status: Accepted · Date: 2026-10-04

## Context

The 2c real-model evaluation (run 37209762015, `qwen3:4b-instruct`) showed that a small model
follows instructions embedded in a request: its *proposals* contained an injected persona
("Root Administrator") and objective ("pwned"). The structural controls held. Skills only
return typed commands, every proposal needs a human decision, and confirmed facts are never
overwritten (ADR-0008). But a reviewer clicking "Accept all" would have added the injected
content to the spec, with model provenance.

Options considered:

1. **A second model as an injection classifier.** It adds latency, cost and another
   component that can itself be injected. Its quality would have to be measured per model,
   and it fails closed or open unpredictably.
2. **Blocking flagged requests.** Business text legitimately contains phrases like "ignore
   duplicates" or "override approval rules". Blocking punishes false positives, and the
   structural controls already prevent damage.
3. **Deterministic, advisory screening plus marking of echoed content** (chosen).

## Decision

- `skill_sdk.safety.scan_text` is a pure function with versioned patterns
  (`injection-scan@1`). It reports signals with offsets and a risk level of `none`,
  `suspicious` or `high`.
- **Advisory, not blocking.** The UI warns while the person types and on the run. The run
  still executes. Skills add a security note after the delimited data, outside it.
- **Echo marking.** After a run, a proposal is marked when it repeats a quoted phrase, or
  two adjacent content words, that occur only in the flagged sentences. Marked proposals
  **start as Reject**. Accepting one is recorded as `ai.flagged_proposals.accepted`.
- **Measured exactly.** A labeled dataset (`evals/datasets/injection/v1.jsonl`) runs in CI
  with enforced floors (precision ≥ 0.95, false-positive rate ≤ 0.05, recall ≥ 0.80).
  Lowering a floor to make a change pass is not allowed.
- **Defence in depth is reported separately from model quality.** Adversarial discovery
  scenarios report whether the model *resisted*, whether its echo was *caught* by marking,
  or whether it *leaked*. An echo still fails the scenario's checks.

## Consequences

- Reviewers see which proposals the injected text may have produced, and the safe choice is
  the default.
- Misses are expected: injections phrased as ordinary requirements, indirect wording, and
  non-English text. They are in the dataset, so recall is not overstated. v1 was written
  together with the detector, so it is a development set; a held-out v2 should follow.
- Only the request message is scanned. Content already in the spec (indirect injection
  through earlier accepted proposals) is not scanned yet.
- If a model-based classifier is ever added, it must beat this baseline on the same
  dataset, and on a held-out set, before it replaces anything.
