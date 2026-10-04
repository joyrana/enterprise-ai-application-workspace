"""Versioned skill registry with deterministic applicability filtering."""

from __future__ import annotations

from appspec import ApplicationSpec, FactStatus
from appspec.common import Tracked

from .skill import Skill, SkillManifest


class RegistryError(ValueError):
    pass


def _known(spec: ApplicationSpec, path: str) -> bool:
    node: object = spec
    for part in path.strip("/").split("/"):
        node = getattr(node, part, None)
        if node is None:
            return False
    if isinstance(node, Tracked):
        return node.status is not FactStatus.UNKNOWN
    if isinstance(node, list):
        return len(node) > 0
    return True


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, dict[str, Skill]] = {}

    def register(self, skill: Skill) -> None:
        manifest = skill.manifest
        versions = self._skills.setdefault(manifest.id, {})
        if manifest.version in versions:
            raise RegistryError(f"skill {manifest.id}@{manifest.version} is already registered")
        for dependency in manifest.depends_on:
            if dependency not in self._skills:
                raise RegistryError(f"skill {manifest.id} depends on unregistered skill {dependency}")
        versions[manifest.version] = skill

    def get(self, skill_id: str, version: str | None = None) -> Skill:
        versions = self._skills.get(skill_id)
        if not versions:
            raise RegistryError(f"unknown skill '{skill_id}'")
        if version is None:
            version = max(versions, key=lambda v: tuple(int(x) for x in v.split(".")))
        try:
            return versions[version]
        except KeyError as exc:
            raise RegistryError(f"unknown version {skill_id}@{version}") from exc

    def manifests(self) -> list[SkillManifest]:
        return sorted(
            (self.get(skill_id).manifest for skill_id in self._skills),
            key=lambda m: (m.category.value, m.id),
        )

    def applicable(self, spec: ApplicationSpec) -> list[SkillManifest]:
        """Latest version of every skill whose preconditions the spec satisfies (no model involved)."""
        return [m for m in self.manifests() if not unmet_preconditions(m, spec)]


def unmet_preconditions(manifest: SkillManifest, spec: ApplicationSpec) -> list[str]:
    return [path for path in manifest.preconditions if not _known(spec, path)]
