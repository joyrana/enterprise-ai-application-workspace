from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from build_runner import BuildReport, ProjectRejected, SandboxLimits, build_archive, docker_argv, run_build, unpack
from build_runner.sandbox import _run_watched, extract_artifacts

TOOLCHAIN = {"dependencies": {"react": "18.3.1"}, "devDependencies": {"vite": "6.4.3"}}


def project_files(**overrides: str) -> dict[str, str]:
    package = {"name": "demo-app", "private": True, **TOOLCHAIN}
    files = {
        "package.json": json.dumps(package),
        "index.html": "<!doctype html><title>Demo</title>",
        "src/main.tsx": "export {};\n",
    }
    files.update(overrides)
    return files


def make_zip(path: Path, files: dict[str, str], manifest: dict[str, str] | None = None, root: str = "demo-r2") -> Path:
    hashes = {p: hashlib.sha256(c.encode()).hexdigest() for p, c in files.items()}
    body = {
        "files": manifest if manifest is not None else hashes,
        "spec_revision": 2,
        "generator": "codegen-react@0.4.0",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in {**files, "workspace-manifest.json": json.dumps(body)}.items():
            zf.writestr(f"{root}/{name}", content)
    return path


def test_unpacks_a_verified_project(tmp_path: Path) -> None:
    archive = make_zip(tmp_path / "app.zip", project_files())
    project = unpack(archive, tmp_path / "out", TOOLCHAIN)
    assert (tmp_path / "out" / "src" / "main.tsx").read_text() == "export {};\n"
    assert project.spec_revision == 2
    assert project.generator == "codegen-react@0.4.0"
    assert set(project.files) == {"package.json", "index.html", "src/main.tsx"}


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("tampered", "manifest"),
        ("extra-file", "manifest"),
        ("extra-dependency", "dependencies"),
        ("overrides", "dependencies"),
        ("no-manifest", "not-generated"),
    ],
)
def test_rejects_projects_that_differ_from_a_generated_one(tmp_path: Path, case: str, code: str) -> None:
    files = project_files()
    hashes = {p: hashlib.sha256(c.encode()).hexdigest() for p, c in files.items()}
    archive = tmp_path / "app.zip"
    if case == "tampered":
        make_zip(archive, {**files, "src/main.tsx": "fetch('https://evil');"}, manifest=hashes)
    elif case == "extra-file":
        make_zip(archive, {**files, "postinstall.js": "x"}, manifest=hashes)
    elif case == "extra-dependency":
        package = {"name": "x", **TOOLCHAIN, "dependencies": {"react": "18.3.1", "left-pad": "1.3.0"}}
        make_zip(archive, project_files(**{"package.json": json.dumps(package)}))
    elif case == "overrides":
        package = {"name": "x", **TOOLCHAIN, "overrides": {"react": "0.0.1"}}
        make_zip(archive, project_files(**{"package.json": json.dumps(package)}))
    else:
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("demo/package.json", "{}")
    with pytest.raises(ProjectRejected) as info:
        unpack(archive, tmp_path / "out", TOOLCHAIN)
    assert info.value.code == code


@pytest.mark.parametrize(
    ("name", "code"),
    [("demo/../../etc/passwd", "unsafe-path"), ("/abs/file", "unsafe-path"), ("loose.txt", "layout")],
)
def test_rejects_unsafe_paths(tmp_path: Path, name: str, code: str) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(name, "x")
    with pytest.raises(ProjectRejected) as info:
        unpack(archive, tmp_path / "out", TOOLCHAIN)
    assert info.value.code == code
    assert not (tmp_path / "etc").exists()


def test_rejects_symlinks_two_roots_bombs_and_non_zips(tmp_path: Path) -> None:
    link = tmp_path / "link.zip"
    with zipfile.ZipFile(link, "w") as zf:
        info = zipfile.ZipInfo("demo/node_modules")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc")
    roots = tmp_path / "roots.zip"
    with zipfile.ZipFile(roots, "w") as zf:
        zf.writestr("a/x", "1")
        zf.writestr("b/y", "2")
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("demo/big.txt", "0" * 1_000_000)
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    for archive, code in [(link, "special-file"), (roots, "layout"), (bomb, "compression-ratio"), (junk, "not-a-zip")]:
        with pytest.raises(ProjectRejected) as info:
            unpack(archive, tmp_path / f"out-{archive.stem}", TOOLCHAIN)
        assert info.value.code == code, archive


def test_container_invocation_is_locked_down(tmp_path: Path) -> None:
    argv = docker_argv("runner:1", tmp_path, SandboxLimits(), "build-x")
    joined = " ".join(argv)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 1000:1000",
        "--memory 1g",
        "--memory-swap 1g",
        "--pids-limit 256",
        "--log-driver none",
    ):
        assert flag in joined, flag
    assert f"type=bind,source={tmp_path.resolve()},target=/src,readonly" in argv
    # The only mounts are the read-only project and size-limited tmpfs; nothing on the host is writable.
    assert [a for a in argv if a.startswith(("type=bind", "type=volume"))] == [
        f"type=bind,source={tmp_path.resolve()},target=/src,readonly"
    ]
    assert "-e" not in argv
    assert "--env" not in argv
    assert "--privileged" not in argv
    assert argv[-1] == "runner:1"


def _tar(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def fake_runner(code: int, stderr: str, stdout: bytes = b"", reason: str | None = None):  # type: ignore[no-untyped-def]
    def run(argv, stdout_path, stderr_path, limits):  # type: ignore[no-untyped-def]
        assert "--network" in argv
        stdout_path.write_bytes(stdout)
        stderr_path.write_text(stderr)
        return code, reason

    return run


def test_successful_build_reports_steps_and_artifact_hashes(tmp_path: Path) -> None:
    stderr = '@@step {"name":"typecheck","exit":0,"ms":900}\nvite v6\n@@step {"name":"build","exit":0,"ms":1500}\n'
    out = _tar({"./index.html": b"<html>", "./assets/app.js": b"console.log(1)"})
    report = run_build(tmp_path, tmp_path / "dist", "runner:1", runner=fake_runner(0, stderr, out))
    assert report.status == "succeeded"
    assert [(s.name, s.exit_code) for s in report.steps] == [("typecheck", 0), ("build", 0)]
    assert report.log_tail == ["vite v6"]
    assert report.artifacts["assets/app.js"] == hashlib.sha256(b"console.log(1)").hexdigest()
    assert (tmp_path / "dist" / "index.html").read_bytes() == b"<html>"
    assert "--network none" in report.isolation
    assert json.loads(report.to_json())["status"] == "succeeded"


def test_failed_timed_out_and_oversized_builds(tmp_path: Path) -> None:
    failed = run_build(
        tmp_path,
        tmp_path / "d1",
        "r",
        runner=fake_runner(1, 'src/a.tsx(1,1): error TS2304\n@@step {"name":"typecheck","exit":2,"ms":5}\n'),
    )
    assert (failed.status, failed.reason) == ("failed", "step 'typecheck' failed")
    assert failed.log_tail == ["src/a.tsx(1,1): error TS2304"]
    timed = run_build(tmp_path, tmp_path / "d2", "r", runner=fake_runner(137, "", reason="timed_out"))
    assert timed.status == "timed_out"
    big = run_build(tmp_path, tmp_path / "d3", "r", runner=fake_runner(137, "", reason="output_too_large"))
    assert big.status == "output_too_large"


def test_build_output_cannot_escape_or_contain_links(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes"):
        extract_artifacts(_tar({"../evil.js": b"x"}), tmp_path / "out", 1000)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(ValueError, match="non-regular"):
        extract_artifacts(buffer.getvalue(), tmp_path / "out2", 1000)
    with pytest.raises(ValueError, match="too large"):
        extract_artifacts(_tar({"a": b"x" * 50}), tmp_path / "out3", 10)
    assert not (tmp_path / "evil.js").exists()


def test_rejected_projects_never_reach_the_container(tmp_path: Path) -> None:
    files = project_files()
    hashes = {p: hashlib.sha256(c.encode()).hexdigest() for p, c in files.items()}
    archive = make_zip(tmp_path / "app.zip", {**files, "src/main.tsx": "tampered"}, manifest=hashes)

    def never(*_args):  # type: ignore[no-untyped-def]
        raise AssertionError("the container must not start")

    report = build_archive(archive, tmp_path / "dist", TOOLCHAIN, runner=never)
    assert isinstance(report, BuildReport)
    assert report.status == "rejected"
    assert report.reason is not None
    assert report.reason.startswith("manifest:")


def test_host_watchdog_kills_a_build_that_runs_too_long(tmp_path: Path) -> None:
    # A stand-in for the container runtime: `run` hangs, `kill` records that it was called.
    docker = tmp_path / "docker"
    marker = tmp_path / "killed"
    docker.write_text(f'#!/bin/sh\nif [ "$1" = kill ]; then touch {marker}; exit 0; fi\nexec sleep 30\n')
    docker.chmod(0o755)
    argv = docker_argv("r", tmp_path, SandboxLimits(), "build-slow", docker=str(docker))
    limits = SandboxLimits(timeout_s=0.5, kill_grace_s=0.5)
    code, reason = _run_watched(argv, tmp_path / "out", tmp_path / "err", limits)
    assert reason == "timed_out"
    assert marker.exists()
    assert code is not None
