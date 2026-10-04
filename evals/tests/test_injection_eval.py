"""The detector is deterministic, so this measures it exactly and guards the floors (ADR-0010 rule 3)."""

from __future__ import annotations

from pathlib import Path

from workspace_evals.injection import (
    DEFAULT_DATASET,
    MAX_FALSE_POSITIVE_RATE,
    MIN_PRECISION,
    MIN_RECALL,
    check_floors,
    load_cases,
    main,
    metrics,
    predict,
)


def test_dataset_is_balanced_enough_and_ids_unique() -> None:
    cases = load_cases(DEFAULT_DATASET)
    assert len({c.id for c in cases}) == len(cases)
    assert sum(c.label == "injection" for c in cases) >= 20
    assert sum(c.label == "benign" for c in cases) >= 15
    # Misses are kept on purpose so recall is not overstated.
    assert any(c.style == "camouflaged" for c in cases)


def test_detector_meets_floors_on_the_dataset() -> None:
    m = metrics(predict(load_cases(DEFAULT_DATASET)))
    assert check_floors(m) == []
    assert m["precision"] >= MIN_PRECISION
    assert m["recall"] >= MIN_RECALL
    assert m["false_positive_rate"] <= MAX_FALSE_POSITIVE_RATE


def test_known_misses_are_reported_not_hidden() -> None:
    m = metrics(predict(load_cases(DEFAULT_DATASET)))
    assert "inj-translated" in m["missed"]


def test_cli_writes_reports(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "injection.json").exists()
    assert "Precision" in (tmp_path / "injection.md").read_text(encoding="utf-8")
