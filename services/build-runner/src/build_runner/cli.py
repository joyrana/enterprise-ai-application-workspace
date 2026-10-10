"""``build-runner build --zip app.zip --toolchain toolchain.json --out dir``: verify, then build in the sandbox."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from .sandbox import BuildReport, Runner, SandboxLimits, _run_watched, run_build
from .verify import ProjectRejected, unpack

DEFAULT_IMAGE = "workspace-build-runner:local"


def build_archive(
    archive: Path,
    output: Path,
    toolchain: dict[str, Any],
    image: str = DEFAULT_IMAGE,
    limits: SandboxLimits | None = None,
    runner: Runner = _run_watched,
) -> BuildReport:
    """Verify ``archive`` and, only if it passes, build it in the sandbox."""
    with tempfile.TemporaryDirectory(prefix="build-src-") as tmp:
        # The container's unprivileged user must be able to read (never write) the project.
        Path(tmp).chmod(0o755)
        source = Path(tmp) / "project"
        try:
            unpack(archive, source, toolchain)
        except ProjectRejected as exc:
            return BuildReport(status="rejected", image=image, reason=f"{exc.code}: {exc}")
        return run_build(source, output, image, limits, runner=runner)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-runner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="verify a generated project zip and build it in the sandbox")
    build.add_argument("--zip", type=Path, required=True)
    build.add_argument("--toolchain", type=Path, required=True, help="the pinned dependencies the image provides")
    build.add_argument("--out", type=Path, required=True, help="folder for the built files and report.json")
    build.add_argument("--image", default=DEFAULT_IMAGE)
    build.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    toolchain = json.loads(args.toolchain.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    report = build_archive(args.zip, args.out / "dist", toolchain, args.image, SandboxLimits(timeout_s=args.timeout))
    (args.out / "report.json").write_text(report.to_json() + "\n", encoding="utf-8")
    print(report.to_json())
    return 0 if report.status == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
