"""Generate a project from a spec file (used by CI to build and browser-test generated apps).

    uv run python -m codegen_react --spec packages/application-spec/examples/finance-operations.json \\
        --out apps/workspace-web/.generated/finance
    ... --without-screens   # derive screens from entities instead (spec screens removed)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from appspec import load_spec
from design_system import get_contract

from .generate import GenerationBlocked, generate_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a React + Fluent 2 project from a spec file.")
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--revision", type=int, default=None)
    parser.add_argument("--without-screens", action="store_true")
    parser.add_argument("--name", default=None, help="Override the application name")
    args = parser.parse_args(argv)

    spec = load_spec(json.loads(args.spec.read_text(encoding="utf-8")))
    if args.without_screens:
        spec = spec.model_copy(update={"screens": [], "navigation": []})
    if args.name:
        spec = spec.model_copy(update={"metadata": spec.metadata.model_copy(update={"name": args.name})})
    contract = get_contract("fluent2")
    assert contract is not None
    try:
        project = generate_project(spec, contract, spec_revision=args.revision)
    except GenerationBlocked as exc:
        for issue in exc.issues:
            print(f"{issue.path}: {issue.code}: {issue.message}", file=sys.stderr)
        return 1
    if args.out.exists():
        shutil.rmtree(args.out)
    for path, content in project.files.items():
        target = args.out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(f"wrote {len(project.files)} files to {args.out} ({len(project.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
