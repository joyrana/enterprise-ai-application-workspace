"""Discovery evaluation: deterministic checks over business-discovery output.

Run against a real model (opt-in; needs a configured model):

    MODEL_PROFILE=ollama MODEL_ID=gpt-oss:20b \\
      uv run python -m workspace_evals.discovery --repeats 3 --out reports/evals

Every check is deterministic and documented in the dataset; no LLM judges here.
Results are only ever produced by actually running a model — the CI tests of
this module use a fake provider to test the harness, never to report quality.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from appspec import ApplicationSpec, load_spec
from model_gateway import Budget, ModelError, ModelProvider, ModelSettings
from skill_sdk import AddItem, AddOpenQuestion, SetFact, SkillContext, SkillOutput
from workspace_skills import BusinessDiscovery

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPO_ROOT / "evals" / "datasets" / "discovery" / "v1.jsonl"
FINANCE_EXAMPLE = REPO_ROOT / "packages" / "application-spec" / "examples" / "finance-operations.json"


class Checks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expect_application: bool
    min_personas: int | None = None
    max_personas: int | None = None
    min_requirements: int | None = None
    max_requirements: int | None = None
    min_open_questions: int | None = None
    max_open_questions: int | None = None
    #: Each inner list is one concept; at least one of its fragments must appear in a requirement title.
    requirements_mention_any: list[list[str]] = Field(default_factory=list)
    forbidden_substrings: list[str] = Field(default_factory=list)
    must_not_propose_paths: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    starting_spec: Literal["empty", "finance-example"]
    description: str
    checks: Checks


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str


class Trial(BaseModel):
    scenario_id: str
    repeat: int
    completed: bool
    error_kind: str | None = None
    checks: list[CheckResult] = Field(default_factory=list)
    latency_ms: float = 0.0
    total_tokens: int = 0
    repaired: bool = False

    @property
    def passed(self) -> bool:
        return self.completed and all(c.passed for c in self.checks)


def load_scenarios(path: Path) -> list[Scenario]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Scenario.model_validate_json(line) for line in lines]


def starting_spec(name: str) -> ApplicationSpec:
    if name == "finance-example":
        return load_spec(json.loads(FINANCE_EXAMPLE.read_text(encoding="utf-8")))
    return ApplicationSpec.empty("Evaluation project")


def _texts(output: SkillOutput) -> list[str]:
    texts: list[str] = []
    for p in output.proposals:
        if isinstance(p, SetFact):
            texts.append(p.value)
        elif isinstance(p, AddItem):
            texts.extend(str(v) for v in p.item.values())
        elif isinstance(p, AddOpenQuestion):
            texts.append(p.question)
    return texts


def evaluate(checks: Checks, output: SkillOutput) -> list[CheckResult]:
    results: list[CheckResult] = []
    is_app = output.not_applicable_reason is None
    results.append(
        CheckResult(
            name="application_classification",
            passed=is_app == checks.expect_application,
            detail=f"expected application={checks.expect_application}, got {is_app}",
        )
    )
    if not checks.expect_application:
        results.append(
            CheckResult(name="no_proposals", passed=not output.proposals, detail=f"{len(output.proposals)} proposals")
        )
        return results

    personas = [p for p in output.proposals if isinstance(p, AddItem) and p.collection == "personas"]
    requirements = [p for p in output.proposals if isinstance(p, AddItem) and p.collection == "functional_requirements"]
    questions = [p for p in output.proposals if isinstance(p, AddOpenQuestion)]

    def bounds(name: str, count: int, low: int | None, high: int | None) -> None:
        if low is None and high is None:
            return
        ok = (low is None or count >= low) and (high is None or count <= high)
        results.append(CheckResult(name=f"{name}_count", passed=ok, detail=f"{count} (allowed {low}..{high})"))

    bounds("personas", len(personas), checks.min_personas, checks.max_personas)
    bounds("requirements", len(requirements), checks.min_requirements, checks.max_requirements)
    bounds("open_questions", len(questions), checks.min_open_questions, checks.max_open_questions)

    titles = [str(p.item.get("title", "")).lower() for p in requirements]
    for concept in checks.requirements_mention_any:
        hit = any(fragment.lower() in title for title in titles for fragment in concept)
        results.append(CheckResult(name=f"mentions:{concept[0]}", passed=hit, detail=f"any of {concept} in titles"))

    corpus = "\n".join(_texts(output))
    for forbidden in checks.forbidden_substrings:
        found = forbidden.lower() in corpus.lower()
        results.append(
            CheckResult(name=f"forbidden:{forbidden}", passed=not found, detail="absent" if not found else "present")
        )

    proposed_paths = {p.path for p in output.proposals if isinstance(p, SetFact)}
    for path in checks.must_not_propose_paths:
        results.append(
            CheckResult(name=f"respects:{path}", passed=path not in proposed_paths, detail="settled fact left alone")
        )
    return results


def run_trial(scenario: Scenario, repeat: int, provider: ModelProvider, *, call_timeout_s: float = 120.0) -> Trial:
    skill = BusinessDiscovery()
    manifest = skill.manifest
    context = SkillContext(
        spec=starting_spec(scenario.starting_spec),
        provider=provider,
        budget=Budget(
            max_calls=manifest.max_model_calls,
            max_total_tokens=manifest.max_total_tokens,
            deadline_s=manifest.timeout_s,
        ),
        call_timeout_s=call_timeout_s,
    )
    started = time.perf_counter()
    try:
        output = skill.run(context, {"description": scenario.description})
    except ModelError as exc:
        return Trial(
            scenario_id=scenario.id,
            repeat=repeat,
            completed=False,
            error_kind=exc.kind.value,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
    model = output.model or {}
    return Trial(
        scenario_id=scenario.id,
        repeat=repeat,
        completed=True,
        checks=evaluate(scenario.checks, output),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
        total_tokens=int((model.get("usage") or {}).get("total_tokens", 0)),
        repaired=bool(model.get("repaired", False)),
    )


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def summarize(trials: list[Trial]) -> dict[str, Any]:
    by_scenario: dict[str, list[Trial]] = {}
    for trial in trials:
        by_scenario.setdefault(trial.scenario_id, []).append(trial)
    latencies = [t.latency_ms for t in trials if t.completed]
    completed = [t for t in trials if t.completed]
    return {
        "trials": len(trials),
        "completion_rate": round(len(completed) / len(trials), 3) if trials else 0.0,
        "pass_rate": round(sum(t.passed for t in trials) / len(trials), 3) if trials else 0.0,
        "repair_rate": round(sum(t.repaired for t in completed) / len(completed), 3) if completed else 0.0,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0.0,
            "p95": round(_p95(latencies), 1),
        },
        "tokens_per_trial_mean": round(statistics.fmean(t.total_tokens for t in completed), 1) if completed else 0.0,
        "errors": {
            k: sum(1 for t in trials if t.error_kind == k)
            for k in sorted({t.error_kind for t in trials if t.error_kind})
        },
        "scenarios": {
            sid: {
                "pass_fraction": round(sum(t.passed for t in group) / len(group), 3),
                "failed_checks": sorted({c.name for t in group for c in t.checks if not c.passed}),
            }
            for sid, group in sorted(by_scenario.items())
        },
    }


def run_suite(
    scenarios: list[Scenario], provider_factory: Callable[[], ModelProvider], *, repeats: int = 1
) -> tuple[list[Trial], dict[str, Any]]:
    trials = [run_trial(s, r, provider_factory()) for r in range(repeats) for s in scenarios]
    return trials, summarize(trials)


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"# Discovery evaluation — {report['model']}",
        "",
        f"- Dataset: `{report['dataset']}` ({report['scenarios']} scenarios x {report['repeats']} repeats)",
        f"- Prompt: `{report['prompt_version']}` · Skill: `{report['skill']}`",
        f"- Run at: {report['run_at']}" + (f" · commit `{report['commit']}`" if report.get("commit") else ""),
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Completion rate | {s['completion_rate']:.0%} |",
        f"| Pass rate (all checks) | {s['pass_rate']:.0%} |",
        f"| Repair rate | {s['repair_rate']:.0%} |",
        f"| Latency mean / p95 | {s['latency_ms']['mean']:.0f} ms / {s['latency_ms']['p95']:.0f} ms |",
        f"| Tokens per trial (mean) | {s['tokens_per_trial_mean']:.0f} |",
        "",
        "| Scenario | Pass fraction | Failed checks |",
        "|---|---|---|",
    ]
    for sid, item in s["scenarios"].items():
        lines.append(f"| {sid} | {item['pass_fraction']:.0%} | {', '.join(item['failed_checks']) or '—'} |")
    if s["errors"]:
        lines += ["", "Errors: " + ", ".join(f"{k}={v}" for k, v in s["errors"].items())]
    lines += ["", "Checks are deterministic; see `evals/datasets/discovery/` for definitions.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate business-discovery against the configured model.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path("reports/evals"))
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be between 1 and 20")

    settings = ModelSettings.from_env()
    if settings is None:
        print("No model configured. Set MODEL_PROFILE and MODEL_ID (see .env.example).", file=sys.stderr)
        return 2
    scenarios = load_scenarios(args.dataset)
    trials, summary = run_suite(scenarios, settings.build_provider, repeats=args.repeats)
    manifest = BusinessDiscovery.manifest
    report = {
        "model": settings.label,
        "skill": f"{manifest.id}@{manifest.version}",
        "prompt_version": manifest.prompt_version,
        "dataset": str(args.dataset.relative_to(REPO_ROOT) if args.dataset.is_relative_to(REPO_ROOT) else args.dataset),
        "scenarios": len(scenarios),
        "repeats": args.repeats,
        "temperature": settings.temperature,
        "structured_mode": settings.structured_mode.value,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA"),
        "summary": summary,
        "trials": [t.model_dump() for t in trials],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"discovery-{settings.label.replace('/', '_').replace(':', '_')}"
    (args.out / f"{stem}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
