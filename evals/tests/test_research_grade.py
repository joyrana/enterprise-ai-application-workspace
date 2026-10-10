from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from workspace_evals import benchmark
from workspace_evals.injection import HOLDOUT_DATASET, load_cases, metrics, predict
from workspace_evals.stats import bootstrap, cohens_h, mcnemar, wilson

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "evals" / "datasets" / "cards.json"


def test_wilson_matches_reference_values() -> None:
    interval = wilson(24, 27)
    assert (round(interval.low, 3), round(interval.high, 3)) == (0.719, 0.961)
    assert wilson(0, 10).low == 0.0
    assert round(wilson(0, 10).high, 3) == 0.278
    assert wilson(10, 10).high == 1.0
    assert wilson(0, 0).n == 0
    with pytest.raises(ValueError, match="successes"):
        wilson(5, 3)


def test_bootstrap_is_seeded_and_mcnemar_is_exact() -> None:
    values = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0]
    assert bootstrap(values) == bootstrap(values)
    assert bootstrap(values).low <= 0.7 <= bootstrap(values).high
    result = mcnemar([True] * 10 + [False] * 3, [True] * 7 + [False] * 6)
    assert (result.a_only, result.b_only, result.p_value) == (3, 0, 0.25)
    assert mcnemar([True, False], [True, False]).p_value == 1.0
    assert round(cohens_h(0.89, 0.61), 2) == 0.67


def test_every_dataset_is_pinned_by_its_card() -> None:
    cards = json.loads(CARDS.read_text(encoding="utf-8"))["datasets"]
    pinned = {c["path"] for c in cards}
    on_disk = {str(p.relative_to(ROOT)) for p in (ROOT / "evals" / "datasets").glob("*/*.jsonl")}
    assert pinned == on_disk, "every dataset file needs a card (and cards must not point at missing files)"
    for card in cards:
        data = (ROOT / card["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == card["sha256"], f"{card['path']} changed: add a new version"
        assert card["cases"] == sum(1 for line in data.decode().splitlines() if line.strip())
        assert card["role"] in ("development", "holdout")


def test_holdout_is_scored_separately_and_reported_honestly() -> None:
    m = metrics(predict(load_cases(HOLDOUT_DATASET)))
    assert m["cases"] == 24
    assert m["intervals"]["recall"]["n"] == 12
    # Whatever the detector scores, the report carries the interval; this pins the reported numbers.
    assert m["false_positives"] == 0
    assert 0.0 <= m["intervals"]["recall"]["low"] <= m["recall"] <= m["intervals"]["recall"]["high"] <= 1.0


def test_benchmark_guarantees_hold_on_every_spec() -> None:
    results = [benchmark.measure(name, raw) for name, raw in benchmark.suite().items()]
    assert len(results) == 6
    for result in results:
        assert result["ir_errors"] == 0, result["spec"]
        for target, entry in result["targets"].items():
            assert entry["generated"], (result["spec"], target, entry.get("error"))
            assert entry["deterministic"]
            assert entry["manifest_ok"]
            assert entry["upgrade_round_trip_ok"]
    summary = benchmark.summarize(results, {(r["spec"], "react"): True for r in results})
    assert summary["react"]["builds"]["estimate"] == 1.0
    assert summary["ir_accessibility_errors"] == 0
