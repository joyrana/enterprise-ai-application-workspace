"""Runs a verified project's build in a locked-down container (ADR-0015).

Isolation, all enforced by the container runtime:

- no network (``--network none``), no host environment, no credentials;
- read-only root filesystem; the project is mounted read-only; work happens on size-limited tmpfs;
- no writable host mount: built files leave as a tar stream on stdout, capped in size;
- an unprivileged user, all capabilities dropped, ``no-new-privileges``;
- memory, CPU, process-count and open-file limits; a wall-clock deadline enforced from the host.

The host never executes project code. It only starts the container, watches the clock and the
output size, and safely unpacks the resulting tar (no links, no paths outside the output folder).
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["succeeded", "failed", "timed_out", "output_too_large", "rejected", "runner_error"]
_STEP = re.compile(r"^@@step (\{.*\})$")


@dataclass(frozen=True)
class SandboxLimits:
    memory: str = "1g"
    cpus: str = "1.0"
    pids: int = 256
    nofile: int = 1024
    work_tmpfs: str = "256m"
    tmp_tmpfs: str = "64m"
    timeout_s: float = 300.0
    max_output_bytes: int = 32 * 1024 * 1024
    max_log_bytes: int = 4 * 1024 * 1024
    kill_grace_s: float = 10.0


@dataclass
class StepResult:
    name: str
    exit_code: int
    duration_ms: int


@dataclass
class BuildReport:
    status: Status
    image: str
    steps: list[StepResult] = field(default_factory=list)
    duration_ms: int = 0
    exit_code: int | None = None
    log_tail: list[str] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)  # path -> sha256
    reason: str | None = None
    isolation: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


def docker_argv(image: str, source: Path, limits: SandboxLimits, name: str, docker: str = "docker") -> list[str]:
    """The exact container invocation. Kept in one place so tests and reports show the real flags."""
    return [
        docker,
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "1000:1000",
        "--memory",
        limits.memory,
        "--memory-swap",
        limits.memory,
        "--cpus",
        limits.cpus,
        "--pids-limit",
        str(limits.pids),
        "--ulimit",
        f"nofile={limits.nofile}:{limits.nofile}",
        "--tmpfs",
        f"/work:rw,noexec,nosuid,nodev,size={limits.work_tmpfs},mode=1777",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmp_tmpfs},mode=1777",  # noqa: S108 - a tmpfs inside the container
        "--mount",
        f"type=bind,source={source.resolve()},target=/src,readonly",
        "--log-driver",
        "none",
        image,
    ]


def isolation_summary(argv: Sequence[str]) -> list[str]:
    flags = []
    for i, arg in enumerate(argv):
        if arg.startswith("--") and arg not in ("--rm", "--name"):
            value = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
            flags.append(f"{arg} {value}".strip() if arg != "--mount" else "--mount <project>:/src (read-only)")
    return flags


def _tail(raw: bytes, lines: int = 200) -> list[str]:
    text = raw.decode("utf-8", "replace").replace("\r", "")
    return [line for line in text.split("\n") if line and not line.startswith("@@step ")][-lines:]


def _steps(raw: bytes) -> list[StepResult]:
    out = []
    for line in raw.decode("utf-8", "replace").splitlines():
        match = _STEP.match(line.strip())
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
            out.append(StepResult(name=str(data["name"]), exit_code=int(data["exit"]), duration_ms=int(data["ms"])))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def extract_artifacts(tar_bytes: bytes, dest: Path, max_bytes: int) -> dict[str, str]:
    """Unpack the build's tar stream: regular files and folders only, nothing outside ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        for member in tar.getmembers():
            name = member.name.removeprefix("./")
            if not name or member.isdir():
                continue
            if not member.isfile():
                raise ValueError(f"build output contains a non-regular file: {member.name!r}")
            target = (dest / name).resolve()
            if not target.is_relative_to(dest.resolve()) or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"build output path escapes the output folder: {member.name!r}")
            total += member.size
            if total > max_bytes:
                raise ValueError("build output is too large")
            source = tar.extractfile(member)
            data = source.read() if source else b""
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
    return dict(sorted(hashes.items()))


Runner = Callable[[list[str], Path, Path, SandboxLimits], tuple[int | None, str | None]]


def _run_watched(
    argv: list[str], stdout_path: Path, stderr_path: Path, limits: SandboxLimits
) -> tuple[int | None, str | None]:
    """Start the container and enforce the deadline and output caps from the host."""
    name = argv[argv.index("--name") + 1]
    docker = argv[0]
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        proc = subprocess.Popen(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL)  # noqa: S603 - fixed argv
        deadline = time.monotonic() + limits.timeout_s
        reason: str | None = None
        while proc.poll() is None:
            if time.monotonic() > deadline:
                reason = "timed_out"
            elif (
                stdout_path.stat().st_size > limits.max_output_bytes
                or stderr_path.stat().st_size > limits.max_log_bytes
            ):
                reason = "output_too_large"
            if reason:
                subprocess.run([docker, "kill", name], capture_output=True, check=False, timeout=30)  # noqa: S603
                try:
                    proc.wait(timeout=limits.kill_grace_s)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
            time.sleep(0.2)
        return proc.returncode, reason


def run_build(
    source: Path,
    output: Path,
    image: str,
    limits: SandboxLimits | None = None,
    docker: str = "docker",
    runner: Runner = _run_watched,
) -> BuildReport:
    """Build the verified project at ``source``; built files land in ``output``."""
    limits = limits or SandboxLimits()
    argv = docker_argv(image, source, limits, f"build-{uuid.uuid4().hex[:12]}", docker)
    report = BuildReport(status="runner_error", image=image, isolation=isolation_summary(argv))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="build-runner-") as tmp:
        stdout_path, stderr_path = Path(tmp) / "stdout.tar", Path(tmp) / "stderr.log"
        try:
            code, reason = runner(argv, stdout_path, stderr_path, limits)
        except (OSError, subprocess.SubprocessError) as exc:
            report.reason = f"could not start the container runtime: {exc}"
            return report
        report.duration_ms = int((time.monotonic() - started) * 1000)
        report.exit_code = code
        stderr = stderr_path.read_bytes()[-limits.max_log_bytes :]
        report.steps = _steps(stderr)
        report.log_tail = _tail(stderr)
        if reason == "timed_out":
            report.status, report.reason = "timed_out", f"the build exceeded {limits.timeout_s:.0f} s"
            return report
        if reason == "output_too_large":
            report.status, report.reason = "output_too_large", "the build produced more output than allowed"
            return report
        if code != 0:
            report.status = "failed"
            failed = next((s.name for s in report.steps if s.exit_code != 0), None)
            report.reason = f"step '{failed}' failed" if failed else f"the container exited with {code}"
            return report
        try:
            report.artifacts = extract_artifacts(stdout_path.read_bytes(), output, limits.max_output_bytes)
        except (ValueError, tarfile.TarError) as exc:
            report.status, report.reason = "failed", f"unusable build output: {exc}"
            return report
    report.status = "succeeded"
    return report
