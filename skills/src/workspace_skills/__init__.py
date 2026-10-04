"""Built-in skills and the default registry."""

from skill_sdk import SkillRegistry

from .discovery import BusinessDiscovery


def default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(BusinessDiscovery())
    return registry


__all__ = ["BusinessDiscovery", "default_registry"]
