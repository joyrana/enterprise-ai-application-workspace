"""Statistics for evaluation reports (Milestone 8). Standard library only, deterministic.

Small evaluation sets make point estimates misleading, so every rate in a report comes with an
interval:

- ``wilson``: Wilson score interval for a proportion (well-behaved at 0 and 1, unlike the
  normal approximation);
- ``bootstrap``: percentile bootstrap interval for any statistic over cases, with a fixed seed
  so reports are reproducible;
- ``mcnemar``: exact (binomial) McNemar test for two methods scored on the *same* cases,
  which is the right test for "is method B better than method A on this set?";
- ``cohens_h``: effect size for a difference between two proportions.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    estimate: float
    low: float
    high: float
    n: int
    method: str
    confidence: float = 0.95

    def as_dict(self) -> dict[str, float | int | str]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}

    def __str__(self) -> str:
        return f"{self.estimate:.1%} [{self.low:.1%}, {self.high:.1%}] (n={self.n})"


def wilson(successes: int, n: int, z: float = Z_95) -> Interval:
    if n < 0 or not 0 <= successes <= max(n, 0):
        raise ValueError("need 0 <= successes <= n")
    if n == 0:
        return Interval(0.0, 0.0, 1.0, 0, "wilson")
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    low = 0.0 if successes == 0 else max(0.0, centre - half)
    high = 1.0 if successes == n else min(1.0, centre + half)
    return Interval(p, low, high, n, "wilson")


def bootstrap(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = lambda v: sum(v) / len(v),
    *,
    resamples: int = 2000,
    seed: int = 20261010,
    confidence: float = 0.95,
) -> Interval:
    """Percentile bootstrap over cases. Deterministic for a given seed."""
    if not values:
        return Interval(0.0, 0.0, 0.0, 0, "bootstrap")
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    n = len(values)
    stats = sorted(statistic([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    alpha = (1 - confidence) / 2
    low = stats[math.floor(alpha * (resamples - 1))]
    high = stats[math.ceil((1 - alpha) * (resamples - 1))]
    return Interval(statistic(values), low, high, n, f"bootstrap(resamples={resamples}, seed={seed})", confidence)


@dataclass(frozen=True)
class McNemar:
    #: Cases method A got right and method B got wrong, and vice versa.
    a_only: int
    b_only: int
    p_value: float

    def as_dict(self) -> dict[str, float | int]:
        return {"a_only": self.a_only, "b_only": self.b_only, "p_value": round(self.p_value, 4)}


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> McNemar:
    """Exact two-sided McNemar test on paired outcomes (same cases, two methods)."""
    if len(a_correct) != len(b_correct):
        raise ValueError("outcomes must be paired")
    a_only = sum(1 for a, b in zip(a_correct, b_correct, strict=True) if a and not b)
    b_only = sum(1 for a, b in zip(a_correct, b_correct, strict=True) if b and not a)
    discordant = a_only + b_only
    if discordant == 0:
        return McNemar(0, 0, 1.0)
    k = min(a_only, b_only)
    tail = sum(math.comb(discordant, i) for i in range(k + 1)) / 2**discordant
    return McNemar(a_only, b_only, min(1.0, 2 * tail))


def cohens_h(p1: float, p2: float) -> float:
    """Effect size for two proportions: ~0.2 small, ~0.5 medium, ~0.8 large."""
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))
