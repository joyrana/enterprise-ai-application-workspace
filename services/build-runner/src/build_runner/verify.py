"""Checks a generated project archive before anything from it runs (ADR-0015).

The archive is untrusted input. It is unpacked only if it is a plain, bounded zip with one
top-level folder, no links or special files and no paths that leave that folder; every file
must match ``workspace-manifest.json``; and ``package.json`` must pin exactly the toolchain the
runner image provides (so nothing is installed and no package scripts exist to run).

The manifest is an integrity check, not authentication: someone can recompute it for a modified
project. That is why the build itself still runs in the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST = "workspace-manifest.json"


class ProjectRejected(Exception):
    """The archive is unsafe or is not an unmodified-shape generated project."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 400
    max_file_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 16 * 1024 * 1024
    max_ratio: int = 100  # uncompressed / compressed, per file (zip bombs)


@dataclass
class VerifiedProject:
    root: Path
    files: dict[str, str] = field(default_factory=dict)  # relative path -> sha256
    spec_revision: int | None = None
    generator: str | None = None


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        raise ProjectRejected("unsafe-path", f"Unsafe path in archive: {name!r}.")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ProjectRejected("unsafe-path", f"Unsafe path in archive: {name!r}.")
    return path


def _check_entries(zf: zipfile.ZipFile, limits: ArchiveLimits) -> tuple[str, list[zipfile.ZipInfo]]:
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise ProjectRejected("empty", "The archive has no files.")
    if len(infos) > limits.max_files:
        raise ProjectRejected("too-many-files", f"The archive has more than {limits.max_files} files.")
    roots: set[str] = set()
    total = 0
    for info in infos:
        path = _safe_name(info.filename)
        if len(path.parts) < 2:
            raise ProjectRejected("layout", "Files must be inside one top-level folder.")
        roots.add(path.parts[0])
        kind = stat.S_IFMT(info.external_attr >> 16)  # 0 when the archiver stored no file type
        if kind and kind != stat.S_IFREG:
            raise ProjectRejected("special-file", f"Links and special files are not allowed: {info.filename!r}.")
        if info.flag_bits & 0x1:
            raise ProjectRejected("encrypted", "Encrypted entries are not allowed.")
        if info.file_size > limits.max_file_bytes:
            raise ProjectRejected("file-too-large", f"{info.filename!r} is larger than {limits.max_file_bytes} bytes.")
        if info.compress_size and info.file_size / info.compress_size > limits.max_ratio:
            raise ProjectRejected("compression-ratio", f"{info.filename!r} expands suspiciously.")
        total += info.file_size
    if total > limits.max_total_bytes:
        raise ProjectRejected("too-large", f"The project is larger than {limits.max_total_bytes} bytes.")
    if len(roots) != 1:
        raise ProjectRejected("layout", "The archive must contain exactly one top-level folder.")
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        raise ProjectRejected("duplicate", "The archive has duplicate entries.")
    return roots.pop(), infos


def _check_package(package: dict[str, Any], toolchain: dict[str, Any]) -> None:
    for group in ("dependencies", "devDependencies"):
        if package.get(group, {}) != toolchain.get(group, {}):
            raise ProjectRejected(
                "dependencies", f"package.json {group} must equal the runner's pinned toolchain exactly."
            )
    for key in ("optionalDependencies", "peerDependencies", "bundledDependencies", "overrides", "workspaces"):
        if key in package:
            raise ProjectRejected("dependencies", f"package.json must not declare {key}.")


def unpack(
    archive: Path, dest: Path, toolchain: dict[str, Any], limits: ArchiveLimits | None = None
) -> VerifiedProject:
    """Validate ``archive`` and unpack its project folder into ``dest`` (which must be empty)."""
    limits = limits or ArchiveLimits()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError(f"{dest} must be empty")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProjectRejected("not-a-zip", "The file is not a readable zip archive.") from exc
    with zf:
        root, infos = _check_entries(zf, limits)
        contents: dict[str, bytes] = {}
        for info in infos:
            relative = str(PurePosixPath(info.filename).relative_to(root))
            data = zf.read(info)
            if len(data) != info.file_size:
                raise ProjectRejected("corrupt", f"{info.filename!r} does not match its declared size.")
            contents[relative] = data

    if MANIFEST not in contents or "package.json" not in contents:
        raise ProjectRejected("not-generated", f"The project has no {MANIFEST} or package.json.")
    try:
        manifest = json.loads(contents[MANIFEST])
        package = json.loads(contents["package.json"])
        declared: dict[str, str] = dict(manifest["files"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ProjectRejected(
            "manifest", "The manifest or package.json is not valid JSON of the expected shape."
        ) from exc

    actual = {p: hashlib.sha256(d).hexdigest() for p, d in contents.items() if p != MANIFEST}
    if set(actual) != set(declared):
        extra, missing = sorted(set(actual) - set(declared)), sorted(set(declared) - set(actual))
        raise ProjectRejected(
            "manifest", f"Files differ from the manifest (extra: {extra[:5]}, missing: {missing[:5]})."
        )
    changed = sorted(p for p in actual if actual[p] != declared[p])
    if changed:
        raise ProjectRejected("manifest", f"Files do not match their manifest hashes: {changed[:5]}.")
    if not isinstance(package, dict):
        raise ProjectRejected("manifest", "package.json must be an object.")
    _check_package(package, toolchain)

    for relative, data in contents.items():
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o644)
    revision = manifest.get("spec_revision")
    return VerifiedProject(
        root=dest,
        files=actual,
        spec_revision=revision if isinstance(revision, int) else None,
        generator=manifest.get("generator") if isinstance(manifest.get("generator"), str) else None,
    )
