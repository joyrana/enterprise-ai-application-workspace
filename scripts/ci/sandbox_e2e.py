"""CI proof for the isolated build runner (ADR-0015). Needs Docker and the runner image.

1. Generates the example app, zips it like the API does, and builds it in the sandbox.
2. Builds a *hostile* project (valid manifest, but its vite.config.ts probes the sandbox) and
   checks that the network is unreachable, the image, the project mount and the root filesystem
   are read-only, no secrets are in the environment, and the build runs as an unprivileged user.
3. Feeds a tampered archive and checks that it is rejected before any container starts.

Writes each report to --out and exits non-zero if any expectation fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from appspec import load_spec
from build_runner import build_archive
from codegen_react import generate_project, toolchain
from design_system import get_contract

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "packages" / "application-spec" / "examples" / "finance-operations.json"

PROBE_CONFIG = """import { writeFileSync } from "node:fs";
import { defineConfig } from "vite";

const results: Record<string, string> = {};
try {
  await fetch("https://example.com/", { signal: AbortSignal.timeout(5000) });
  results.network = "open";
} catch {
  results.network = "blocked";
}
for (const [name, path] of [["toolchain", "/toolchain/probe"], ["source", "/src/probe"], ["rootfs", "/probe"]]) {
  try {
    writeFileSync(path, "x");
    results[name] = "writable";
  } catch {
    results[name] = "read-only";
  }
}
const suspicious = Object.keys(process.env).filter((k) => /TOKEN|SECRET|PASSWORD|KEY|GITHUB|ACTIONS/i.test(k));
results.secrets = suspicious.length ? suspicious.join(",") : "none";
results.uid = String(process.getuid ? process.getuid() : -1);
console.error("@@probe " + JSON.stringify(results));

export default defineConfig({});
"""


def write_zip(path: Path, files: dict[str, str], root: str) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in sorted(files.items()):
            zf.writestr(f"{root}/{name}", content)
    return path


def with_manifest(files: dict[str, str]) -> dict[str, str]:
    manifest = json.loads(files["workspace-manifest.json"])
    body = {p: c for p, c in files.items() if p != "workspace-manifest.json"}
    manifest["files"] = {p: hashlib.sha256(c.encode("utf-8")).hexdigest() for p, c in body.items()}
    return {**body, "workspace-manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("reports/build-runner"))
    parser.add_argument("--image", default="workspace-build-runner:local")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    contract = get_contract("fluent2")
    assert contract is not None
    spec = load_spec(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    files = dict(generate_project(spec, contract, spec_revision=2).files)
    tools = toolchain()
    failures: list[str] = []

    def build(name: str, project: dict[str, str]) -> dict[str, object]:
        archive = write_zip(args.out / f"{name}.zip", project, f"{name}-r2")
        report = build_archive(archive, args.out / name / "dist", tools, image=args.image)
        (args.out / f"{name}.json").write_text(report.to_json() + "\n", encoding="utf-8")
        print(f"::group::{name}: {report.status}\n{report.to_json()}\n::endgroup::")
        return json.loads(report.to_json())

    good = build("example", files)
    if good["status"] != "succeeded":
        failures.append(f"example app did not build: {good['reason']}")
    elif "index.html" not in good["artifacts"]:  # type: ignore[operator]
        failures.append("example build produced no index.html")

    hostile = build("hostile", with_manifest({**files, "vite.config.ts": PROBE_CONFIG}))
    probe_lines = [line for line in hostile["log_tail"] if str(line).startswith("@@probe ")]  # type: ignore[union-attr]
    if not probe_lines:
        failures.append("hostile project: the probe did not run (no @@probe line)")
    else:
        probe = json.loads(str(probe_lines[-1]).removeprefix("@@probe "))
        expected = {
            "network": "blocked",
            "toolchain": "read-only",
            "source": "read-only",
            "rootfs": "read-only",
            "secrets": "none",
        }
        for key, value in expected.items():
            if probe.get(key) != value:
                failures.append(f"hostile project: {key} is {probe.get(key)!r}, expected {value!r}")
        if probe.get("uid") in ("0", "-1"):
            failures.append(f"hostile project: build ran as uid {probe.get('uid')}")
        print(f"::notice title=sandbox probe::{json.dumps(probe, sort_keys=True)}")

    tampered = dict(files)
    tampered["src/main.tsx"] = tampered["src/main.tsx"] + "\nfetch('https://attacker.example/');\n"
    rejected = build("tampered", tampered)
    if rejected["status"] != "rejected":
        failures.append(f"tampered archive was not rejected: {rejected['status']}")

    for failure in failures:
        print(f"::error title=build runner::{failure}")
    if not failures:
        print("::notice title=build runner::example built; hostile probes contained; tampered archive rejected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
