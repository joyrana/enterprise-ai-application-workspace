"""Routing evaluation: does the workspace pick the right skill (or none)?

Two methods share stage 1 (precondition filtering, deterministic):

* ``lexical`` — keyword-overlap baseline. Deterministic; runs anywhere, including CI.
* ``router``  — the production router (model chooses among candidates). Needs a configured model.

    uv run python -m workspace_evals.routing --method lexical
    MODEL_PROFILE=ollama MODEL_ID=gpt-oss:20b uv run python -m workspace_evals.routing --method router --repeats 3

Thresholds are deliberately not enforced yet: the brief requires collecting a baseline first.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from model_gateway import Budget, ModelError, ModelProvider, ModelSettings
from skill_sdk import NONE, ROUTER_PROMPT_VERSION, SkillRouter, lexical_choice
from workspace_skills import default_registry

from .discovery import REPO_ROOT, starting_spec
from .stats import bootstrap

DEFAULT_DATASET = REPO_ROOT / "evals" / "datasets" / "routing" / "v2.jsonl"
Method = Literal["lexical", "router"]


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    spec_state: Literal["empty", "finance-example"]
    message: str
    expected: str


class Prediction(BaseModel):
    case_id: str
    repeat: int
    expected: str
    predicted: str | None  # None = the method failed (error), distinct from the label "none"
    stage: str
    error_kind: str | None = None
    #: The gateway's diagnostic (e.g. which field failed validation). Eval data is synthetic, so it may be shown.
    error_detail: str | None = None
    model_calls: int = 0
    latency_ms: float = 0.0
    total_tokens: int = 0


def load_cases(path: Path = DEFAULT_DATASET) -> list[Case]:
    return [Case.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def predict(
    case: Case, repeat: int, method: Method, provider: ModelProvider | None, *, deadline_s: float = 60.0
) -> Prediction:
    registry = default_registry()
    spec = starting_spec(case.spec_state)
    started = time.perf_counter()
    if method == "lexical":
        candidates = registry.applicable(spec)
        if len(candidates) <= 1:
            label = candidates[0].id if candidates else NONE
            stage = "single-candidate" if candidates else "no-candidates"
        else:
            choice, _ = lexical_choice(case.message, candidates)
            label, stage = choice or NONE, "lexical"
        return Prediction(case_id=case.id, repeat=repeat, expected=case.expected, predicted=label, stage=stage)
    try:
        decision = SkillRouter(registry).route(
            case.message,
            spec,
            provider=provider,
            budget=Budget(max_calls=2, deadline_s=deadline_s),
            call_timeout_s=deadline_s,
        )
    except ModelError as exc:
        return Prediction(
            case_id=case.id,
            repeat=repeat,
            expected=case.expected,
            predicted=None,
            stage="error",
            error_kind=exc.kind.value,
            error_detail=(exc.detail or "")[:240] or None,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    model = decision.model or {}
    return Prediction(
        case_id=case.id,
        repeat=repeat,
        expected=case.expected,
        predicted=decision.skill_id or NONE,
        stage=decision.method,
        model_calls=len(model.get("calls", [])),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        total_tokens=int((model.get("usage") or {}).get("total_tokens", 0)),
    )


def metrics(predictions: list[Prediction]) -> dict[str, Any]:
    total = len(predictions)
    correct = sum(p.predicted == p.expected for p in predictions)
    labels = sorted({p.expected for p in predictions} | {p.predicted for p in predictions if p.predicted})
    per_label: dict[str, dict[str, float | int]] = {}
    for label in labels:
        tp = sum(p.predicted == label and p.expected == label for p in predictions)
        fp = sum(p.predicted == label and p.expected != label for p in predictions)
        fn = sum(p.predicted != label and p.expected == label for p in predictions)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_label[label] = {
            "support": tp + fn,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0,
        }
    expected_none = [p for p in predictions if p.expected == NONE]
    expected_skill = [p for p in predictions if p.expected != NONE]
    routed = [p for p in predictions if p.stage == "model"]
    return {
        "cases": total,
        "accuracy": round(correct / total, 3) if total else 0.0,
        "accuracy_ci": _accuracy_ci(predictions),
        "correct": correct,
        "errors": dict(Counter(p.error_kind for p in predictions if p.error_kind)),
        "false_invocation_rate": round(
            sum(p.predicted not in (NONE, None) for p in expected_none) / len(expected_none), 3
        )
        if expected_none
        else 0.0,
        "missed_invocation_rate": round(sum(p.predicted == NONE for p in expected_skill) / len(expected_skill), 3)
        if expected_skill
        else 0.0,
        "model_calls": sum(p.model_calls for p in predictions),
        "model_routed_cases": len(routed),
        "latency_ms_mean_model_routed": round(statistics.fmean(p.latency_ms for p in routed), 1) if routed else 0.0,
        "per_label": per_label,
        "error_details": [
            {"case_id": p.case_id, "repeat": p.repeat, "kind": p.error_kind, "detail": p.error_detail}
            for p in predictions
            if p.error_kind
        ],
        **_variance(predictions),
        "confusion": {
            f"{expected} -> {predicted}": n
            for (expected, predicted), n in sorted(
                Counter((p.expected, str(p.predicted)) for p in predictions if p.predicted != p.expected).items()
            )
        },
    }


def _accuracy_ci(predictions: list[Prediction]) -> dict[str, Any]:
    """95% bootstrap interval over *cases* (repeats of one case are averaged first, not counted as
    independent samples)."""
    by_case: dict[str, list[bool]] = {}
    for p in predictions:
        by_case.setdefault(p.case_id, []).append(p.predicted == p.expected)
    case_means = [sum(v) / len(v) for _, v in sorted(by_case.items())]
    return bootstrap(case_means).as_dict()


def _variance(predictions: list[Prediction]) -> dict[str, Any]:
    """Accuracy per repeat and cases whose prediction changed between repeats."""
    repeats = sorted({p.repeat for p in predictions})
    by_repeat = []
    for r in repeats:
        group = [p for p in predictions if p.repeat == r]
        by_repeat.append(round(sum(p.predicted == p.expected for p in group) / len(group), 3))
    outcomes: dict[str, set[str]] = {}
    for p in predictions:
        outcomes.setdefault(p.case_id, set()).add(str(p.predicted))
    return {
        "accuracy_by_repeat": by_repeat,
        "accuracy_stdev": round(statistics.pstdev(by_repeat), 3) if len(by_repeat) > 1 else 0.0,
        "unstable_cases": sorted(cid for cid, seen in outcomes.items() if len(seen) > 1),
    }


def run(
    cases: list[Case],
    method: Method,
    provider_factory: Callable[[], ModelProvider] | None,
    *,
    repeats: int = 1,
    deadline_s: float = 60.0,
) -> tuple[list[Prediction], dict[str, Any]]:
    predictions = [
        predict(case, r, method, provider_factory() if provider_factory else None, deadline_s=deadline_s)
        for r in range(repeats)
        for case in cases
    ]
    return predictions, metrics(predictions)


def summary_line(method: str, label: str, m: dict[str, Any]) -> str:
    return (
        f"routing[{method}:{label}] accuracy {m['accuracy']:.0%} ({m['correct']}/{m['cases']}), "
        f"false invocations {m['false_invocation_rate']:.0%}, missed {m['missed_invocation_rate']:.0%}, "
        f"model calls {m['model_calls']}, errors {m['errors'] or 'none'}"
    )


def markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lines = [
        f"# Routing evaluation — {report['method']} ({report['model'] or 'no model'})",
        "",
        f"- Dataset: `{report['dataset']}` ({m['cases']} predictions, {report['repeats']} repeat(s))",
        f"- Router prompt: `{report['router_prompt_version']}` · Run at: {report['run_at']}"
        + (f" · commit `{report['commit']}`" if report.get("commit") else ""),
        "",
        f"**{summary_line(report['method'], report['model'] or 'none', m)}**",
        "",
        "| Label | Support | Precision | Recall | F1 |",
        "|---|---|---|---|---|",
    ]
    for label, s in m["per_label"].items():
        lines.append(f"| {label} | {s['support']} | {s['precision']:.2f} | {s['recall']:.2f} | {s['f1']:.2f} |")
    if m["errors"]:
        errors = ", ".join(f"{k} x{v}" for k, v in m["errors"].items())
        lines += ["", f"Errors (method failed, counted as wrong): {errors}"]
    if m["confusion"]:
        lines += ["", "Misroutes: " + ", ".join(f"{k} x{v}" for k, v in m["confusion"].items())]
    if len(m["accuracy_by_repeat"]) > 1:
        per = ", ".join(f"{a:.0%}" for a in m["accuracy_by_repeat"])
        lines += [
            "",
            f"Accuracy by repeat: {per} (population stdev {m['accuracy_stdev']:.3f}); "
            f"cases that changed between repeats: {', '.join(m['unstable_cases']) or 'none'}",
        ]
    if m["error_details"]:
        lines += ["", "Error details:"]
        lines += [
            f"- `{e['case_id']}` (repeat {e['repeat']}): {e['kind']}: {e['detail'] or 'no detail'}"
            for e in m["error_details"]
        ]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate skill routing.")
    parser.add_argument("--method", choices=["lexical", "router"], default="lexical")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("reports/evals"))
    parser.add_argument("--deadline-s", type=float, default=60.0, help="Routing deadline per case (recorded).")
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")

    settings = None
    factory = None
    if args.method == "router":
        settings = ModelSettings.from_env()
        if settings is None:
            print("The router method needs a configured model (MODEL_PROFILE, MODEL_ID).", file=sys.stderr)
            return 2
        factory = settings.build_provider
    cases = load_cases(args.dataset)
    predictions, m = run(cases, args.method, factory, repeats=args.repeats, deadline_s=args.deadline_s)
    report = {
        "method": args.method,
        "model": settings.label if settings else None,
        "router_prompt_version": ROUTER_PROMPT_VERSION,
        "dataset": str(args.dataset.relative_to(REPO_ROOT) if args.dataset.is_relative_to(REPO_ROOT) else args.dataset),
        "repeats": args.repeats,
        "deadline_s": args.deadline_s,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA"),
        "metrics": m,
        "predictions": [p.model_dump() for p in predictions],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"routing-{args.method}" + (f"-{settings.label.replace('/', '_').replace(':', '_')}" if settings else "")
    (args.out / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    print(summary_line(args.method, settings.label if settings else "none", m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
