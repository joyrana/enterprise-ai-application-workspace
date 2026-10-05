"""Built-in skills and the default registry."""

from skill_sdk import SkillRegistry

from .discovery import AcceptanceCriteria, BusinessDiscovery, ConflictDetection
from .experience import ScreenDesign


def default_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(BusinessDiscovery())
    registry.register(AcceptanceCriteria())
    registry.register(ConflictDetection())
    registry.register(ScreenDesign())
    return registry


__all__ = ["AcceptanceCriteria", "BusinessDiscovery", "ConflictDetection", "ScreenDesign", "default_registry"]
