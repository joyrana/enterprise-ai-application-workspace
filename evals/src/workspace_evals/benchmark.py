"""End-to-end benchmark: specification → UI IR → generated React and Angular apps (Milestone 8).

Deterministic and model-free. It measures what the pipeline guarantees, on a fixed suite of
specifications covering different shapes (specified screens, entity-only apps, validation
rules, Angular, a second domain, and every field type):

- the UI IR validates, with no accessibility errors;
- both generators produce output;
- generating twice gives byte-identical files;
- the manifest hashes match the files;
- upgrading an untouched copy (ADR-0016) returns the regenerated project unchanged.

``--write-projects`` writes every generated project to disk, so CI can build each one with the
real toolchains and record the build outcomes. ``--builds`` merges those outcomes back into the
report, with 95% Wilson intervals on the success rates.

    uv run python -m workspace_evals.benchmark --out reports/benchmark --write-projects .generated/benchmark
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from appspec import ApplicationSpec, load_spec
from codegen_angular import generate_project as generate_angular
from codegen_react import MANIFEST, GeneratedProject, merge_projects
from codegen_react import generate_project as generate_react
from design_system import derive_document, get_contract, validate_document

from .discovery import REPO_ROOT
from .stats import wilson

BENCHMARK_VERSION = "1"
EXAMPLE = REPO_ROOT / "packages" / "application-spec" / "examples" / "finance-operations.json"
USER = {"source": "user", "actor": "benchmark"}


def _base() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return data


def suite() -> dict[str, dict[str, Any]]:
    """The fixed benchmark specifications, derived deterministically from the example."""
    specs: dict[str, dict[str, Any]] = {}
    specs["finance-screens"] = _base()

    entities = _base()
    entities["screens"], entities["navigation"] = [], []
    specs["finance-entities"] = entities

    validations = _base()
    validations["screens"][0]["components"] = [{"id": "edit", "kind": "form"}]
    validations["screens"][0]["fields"] = [
        {
            "name": "reference",
            "label": "Reference",
            "type": "string",
            "validation": [{"kind": "required"}, {"kind": "max-length", "value": 12}],
        },
        {"name": "count", "label": "Count", "type": "integer", "validation": [{"kind": "min", "value": 1}]},
        {"name": "notes", "label": "Notes", "type": "text", "validation": [{"kind": "max-length", "value": 500}]},
    ]
    specs["finance-validations"] = validations

    angular = _base()
    angular["framework"]["framework"] = {"value": "angular", "status": "proposed", "provenance": USER}
    specs["finance-angular"] = angular

    leave = _base()
    leave["metadata"]["name"] = "Leave Requests"
    leave["screens"], leave["navigation"] = [], []
    leave["entities"] = [
        {
            "id": "leave-request",
            "name": "Leave request",
            "status": "proposed",
            "provenance": USER,
            "fields": [
                {"name": "employee", "type": "string", "required": True},
                {"name": "start-date", "type": "date", "required": True},
                {"name": "end-date", "type": "date"},
                {"name": "days", "type": "decimal"},
                {"name": "kind", "type": "enum", "enum_values": ["annual", "sick", "unpaid"], "required": True},
                {"name": "reason", "type": "text"},
                {"name": "approved", "type": "boolean"},
            ],
        }
    ]
    specs["leave-requests"] = leave

    wide = _base()
    wide["metadata"]["name"] = "Asset Register"
    wide["screens"], wide["navigation"] = [], []
    types = ["string", "text", "integer", "decimal", "money", "boolean", "date", "datetime"]
    fields: list[dict[str, Any]] = [
        {"name": f"{t}-{i}", "type": t, "required": i == 0} for i in range(3) for t in types
    ]
    fields.append({"name": "category", "type": "enum", "enum_values": ["it", "facility", "vehicle"]})
    fields.append({"name": "owner", "type": "reference", "reference_entity_id": "person"})
    wide["entities"] = [
        {"id": "asset", "name": "Asset", "status": "proposed", "provenance": USER, "fields": fields},
        {
            "id": "person",
            "name": "Person",
            "status": "proposed",
            "provenance": USER,
            "fields": [{"name": "full-name", "type": "string", "required": True}],
        },
    ]
    specs["asset-register"] = wide
    return specs


def _manifest_ok(project: GeneratedProject) -> bool:
    manifest = json.loads(project.files[MANIFEST])
    files = {p: c for p, c in project.files.items() if p != MANIFEST}
    return set(manifest["files"]) == set(files) and all(
        hashlib.sha256(files[p].encode("utf-8")).hexdigest() == h for p, h in manifest["files"].items()
    )


def _round_trip_ok(project: GeneratedProject) -> bool:
    hashes = json.loads(project.files[MANIFEST])["files"]
    merged = merge_projects(
        dict(project.files), dict(project.files), dict(project.files), hashes, "regenerated", frozenset({MANIFEST})
    )
    return merged.files == project.files and merged.conflicts == 0


def measure(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    spec: ApplicationSpec = load_spec(copy.deepcopy(raw))
    document = derive_document(spec, spec_revision=1)
    issues = validate_document(document, spec)
    errors = [i for i in issues if i.severity == "error"]
    result: dict[str, Any] = {
        "spec": name,
        "screens": len(document.screens),
        "entities": len(spec.entities),
        "ir_errors": len(errors),
        "ir_accessibility_errors": sum(1 for i in errors if i.code.startswith("a11y-")),
        "ir_warnings": len(issues) - len(errors),
        "targets": {},
    }
    for target, generate, contract_id in (
        ("react", generate_react, "fluent2"),
        ("angular", generate_angular, "material3"),
    ):
        contract = get_contract(contract_id)
        assert contract is not None
        entry: dict[str, Any] = {"generated": False}
        try:
            first = generate(spec, contract, spec_revision=1, document=document)
            second = generate(spec, contract, spec_revision=1, document=document)
        except Exception as exc:  # recorded, never hidden
            entry["error"] = f"{type(exc).__name__}: {exc}"
        else:
            entry.update(
                generated=True,
                files=len(first.files),
                deterministic=first.files == second.files,
                manifest_ok=_manifest_ok(first),
                upgrade_round_trip_ok=_round_trip_ok(first),
                warnings=len(first.warnings),
                generator=first.generator,
            )
            entry["_project"] = first
        result["targets"][target] = entry
    return result


def summarize(results: list[dict[str, Any]], builds: dict[tuple[str, str], bool] | None = None) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for target in ("react", "angular"):
        entries = [r["targets"][target] for r in results]
        n = len(entries)
        block: dict[str, Any] = {}
        for metric in ("generated", "deterministic", "manifest_ok", "upgrade_round_trip_ok"):
            ok = sum(1 for e in entries if e.get(metric))
            block[metric] = wilson(ok, n).as_dict()
        if builds:
            outcomes = [builds[(r["spec"], target)] for r in results if (r["spec"], target) in builds]
            block["builds"] = wilson(sum(outcomes), len(outcomes)).as_dict()
            block["failed_builds"] = sorted(r["spec"] for r in results if builds.get((r["spec"], target)) is False)
        summary[target] = block
    summary["ir_accessibility_errors"] = sum(r["ir_accessibility_errors"] for r in results)
    return summary


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# End-to-end benchmark v{report['benchmark_version']}",
        "",
        f"{len(report['results'])} specifications · commit `{report['commit']}` · generated {report['generated_at']}",
        "",
        "Rates are successes/total with 95% Wilson intervals. Small n: treat as evidence of the guarantees, not as "
        "a quality score.",
        "",
        "| Metric | React + Fluent 2 | Angular + Material 3 |",
        "|---|---|---|",
    ]
    s = report["summary"]
    for metric, label in (
        ("generated", "Generated"),
        ("deterministic", "Byte-identical on regeneration"),
        ("manifest_ok", "Manifest hashes match"),
        ("upgrade_round_trip_ok", "Upgrade of an untouched copy is a no-op"),
        ("builds", "Builds with the locked toolchain (CI)"),
    ):
        if metric not in s["react"]:
            continue
        cells = []
        for target in ("react", "angular"):
            i = s[target][metric]
            cells.append(f"{round(i['estimate'] * i['n'])}/{i['n']} [{i['low']:.0%}, {i['high']:.0%}]")
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")
    lines += ["", f"IR accessibility errors across the suite: {s['ir_accessibility_errors']}", ""]
    lines += ["| Spec | Screens | Entities | IR warnings | React files | Angular files |", "|---|---|---|---|---|---|"]
    for r in report["results"]:
        lines.append(
            f"| {r['spec']} | {r['screens']} | {r['entities']} | {r['ir_warnings']} | "
            f"{r['targets']['react'].get('files', '—')} | {r['targets']['angular'].get('files', '—')} |"
        )
    return "\n".join(lines) + "\n"


def _commit() -> str:
    import os
    import subprocess

    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"][:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=False)  # noqa: S607
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("reports/benchmark"))
    parser.add_argument("--write-projects", type=Path, default=None)
    parser.add_argument(
        "--builds", type=Path, default=None, help="TSV of spec, target, ok|failed from the CI build step"
    )
    args = parser.parse_args(argv)

    results = [measure(name, raw) for name, raw in suite().items()]
    if args.write_projects:
        for r in results:
            for target, entry in r["targets"].items():
                project = entry.get("_project")
                if project is None:
                    continue
                folder = args.write_projects / f"{r['spec']}-{target}"
                for path, content in project.files.items():
                    file = folder / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(content, encoding="utf-8")
    for r in results:
        for entry in r["targets"].values():
            entry.pop("_project", None)
    builds: dict[tuple[str, str], bool] | None = None
    if args.builds and args.builds.exists():
        builds = {}
        for line in args.builds.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                builds[(parts[0], parts[1])] = parts[2] == "ok"
    report: dict[str, Any] = {
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _commit(),
        "results": results,
        "summary": summarize(results, builds),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (args.out / "benchmark.md").write_text(markdown(report), encoding="utf-8")
    react, angular = report["summary"]["react"], report["summary"]["angular"]
    line = (
        f"benchmark[v{BENCHMARK_VERSION}] {len(results)} specs; generated react "
        f"{round(react['generated']['estimate'] * len(results))}/{len(results)}, angular "
        f"{round(angular['generated']['estimate'] * len(results))}/{len(results)}"
    )
    if builds:
        line += (
            f"; builds react {round(react['builds']['estimate'] * react['builds']['n'])}/{react['builds']['n']}, "
            f"angular {round(angular['builds']['estimate'] * angular['builds']['n'])}/{angular['builds']['n']}"
        )
    print(line)
    failures = [
        f"{r['spec']}/{t}: {e.get('error') or 'guarantee broken'}"
        for r in results
        for t, e in r["targets"].items()
        if not (
            e.get("generated") and e.get("deterministic") and e.get("manifest_ok") and e.get("upgrade_round_trip_ok")
        )
    ]
    if builds:
        failures += [f"{spec}/{target}: build failed" for (spec, target), ok in sorted(builds.items()) if not ok]
    for failure in failures:
        print(f"benchmark failure: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
