# Evaluation protocol

This document fixes *how* the workspace is evaluated, before results are read, so numbers
cannot be shaped after the fact. It complements the evidence tiers in ADR-0010.

## Principles

1. **State the claim, then measure it.** Every metric below names the claim it supports. A
   number without its claim is not reported.
2. **Intervals, not just point estimates.**
   - Proportions get 95% Wilson score intervals.
   - Aggregates over cases get a seeded percentile bootstrap (2,000 resamples, seed
     20261010), with repeats of one case averaged before resampling.
   - Comparisons of two methods on the same cases use the exact McNemar test, with Cohen's h
     as the effect size.
   - Code: `workspace_evals.stats`.
3. **Development and holdout are separate.**
   - Datasets used while building a component are *development* sets. Their numbers are
     upper bounds.
   - *Holdout* sets are written and committed before the component is scored on them, and
     are never used for tuning.
   - Once a holdout result is published, the next version of the component needs a new
     holdout.
4. **Data is pinned.** `evals/datasets/cards.json` records every dataset's SHA-256, size,
   role, provenance and limitations. A test fails if a file changes; changed data means a
   new version file, never an edit in place.
5. **Model results carry their conditions.** Reports record the model, provider, prompt
   version, repeats and date. Real-model numbers are never mixed with scripted-model numbers
   (ADR-0010).
6. **Negative results are reported.** Misses, failures and weak spots are listed by id in
   every report.

## Hypotheses and metrics

| Claim | Metric | Data | Threshold |
|---|---|---|---|
| The injection screen rarely flags ordinary business language | Precision and false-positive rate | Injection v1 (development) | Precision ≥ 0.95, FPR ≤ 0.05, enforced in CI |
| The screen catches common injection styles | Recall | Injection v1 (development) | ≥ 0.80, enforced in CI |
| The screen generalizes to unseen phrasings | Recall on the holdout, with an interval | Injection holdout-v1 | Reported; no threshold (it is the honest estimate) |
| Routing picks the right skill | Accuracy with a case-level bootstrap interval; false and missed invocation rates | Routing v2 | Lexical baseline reported in CI; model router opt-in |
| The pipeline's guarantees hold across app shapes | Generated, byte-identical, manifest hashes match, upgrade round trip is a no-op | Benchmark v1 (6 specs × 2 targets) | 100%, enforced in CI |
| Generated apps build with the locked toolchains | Build success | Benchmark v1 | 100%, enforced in CI |
| Generated apps are accessible | Serious or critical axe violations on every route | Example apps in CI | 0, enforced in CI |

## Current results

[docs/status.md](../status.md) records each milestone's results with run links.

The first holdout result (the set was written on 2026-10-10 and committed on its own, before the commit that scores it):
- The injection screen keeps 100% precision (0 false positives in 12 benign cases).
- Recall drops to 33% (4/12, 95% CI [14%, 61%]), against 89% on the development set.
- It misses multilingual, indirect, obfuscated, tool-spoofing and authority-claim phrasings.

This confirms the design in ADR-0011: the screen is advisory, and human review and structural
controls are the boundary. The detector was **not** changed in response.

## Not yet measured

- **Model quality on the holdout-style tasks:** this needs the opt-in real-model workflow and
  a token for the hosted Qwen provider.
- **Usability of generated apps with people:** only automated accessibility is measured.
- **Inter-annotator agreement on labels:** all labels so far come from one author.
