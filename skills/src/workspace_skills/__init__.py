"""Built-in skills and the default registry."""

from skill_sdk import SkillRegistry

from .discovery import AcceptanceCriteria, BusinessDiscovery, ConflictDetection


def default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(BusinessDiscovery())
    registry.register(AcceptanceCriteria())
    registry.register(ConflictDetection())
    return registry


__all__ = ["AcceptanceCriteria", "BusinessDiscovery", "ConflictDetection", "default_registry"]
