"""Canonical application specification, schema version 1.0.0.

This is the single source of truth for a project. It is framework-neutral: it
says *what* the application must do and which design system it targets, never
how a particular framework renders it (that belongs to the UI intermediate
representation introduced in a later milestone).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from .common import (
    Identifier,
    LongText,
    ShortText,
    StrictModel,
    Tracked,
    TrackedItem,
)

SCHEMA_VERSION = "1.0.0"


# --------------------------------------------------------------------------- enums


class Priority(StrEnum):
    MUST = "must"
    SHOULD = "should"
    COULD = "could"
    WONT = "wont"


class NfrCategory(StrEnum):
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    SECURITY = "security"
    PRIVACY = "privacy"
    COMPLIANCE = "compliance"
    ACCESSIBILITY = "accessibility"
    USABILITY = "usability"
    SCALABILITY = "scalability"
    OBSERVABILITY = "observability"
    MAINTAINABILITY = "maintainability"
    OTHER = "other"


class FieldType(StrEnum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    MONEY = "money"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    ENUM = "enum"
    FILE = "file"
    REFERENCE = "reference"


class UiState(StrEnum):
    LOADING = "loading"
    EMPTY = "empty"
    ERROR = "error"
    SUCCESS = "success"
    DISABLED = "disabled"


class Framework(StrEnum):
    REACT = "react"
    ANGULAR = "angular"


class Classification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# --------------------------------------------------------------------------- sections


class ProjectMetadata(StrictModel):
    name: ShortText
    description: LongText | None = None
    tags: list[ShortText] = Field(default_factory=list, max_length=20)


class Persona(TrackedItem):
    name: ShortText
    description: LongText | None = None
    goals: list[ShortText] = Field(default_factory=list)
    role_ids: list[Identifier] = Field(default_factory=list)


class Role(TrackedItem):
    name: ShortText
    description: LongText | None = None


class JourneyStep(StrictModel):
    description: ShortText
    screen_id: Identifier | None = None


class UserJourney(TrackedItem):
    name: ShortText
    persona_ids: list[Identifier] = Field(default_factory=list)
    steps: list[JourneyStep] = Field(default_factory=list)


class FunctionalRequirement(TrackedItem):
    title: ShortText
    description: LongText | None = None
    priority: Priority = Priority.SHOULD
    persona_ids: list[Identifier] = Field(default_factory=list)


class NonFunctionalRequirement(TrackedItem):
    category: NfrCategory
    statement: LongText
    measure: ShortText | None = Field(default=None, description="How compliance is measured, e.g. 'p95 < 300 ms'.")


class AcceptanceCriterion(TrackedItem):
    requirement_id: Identifier
    given: LongText
    when: LongText
    then: LongText


class BusinessRule(TrackedItem):
    statement: LongText
    requirement_ids: list[Identifier] = Field(default_factory=list)


class EntityField(StrictModel):
    name: Identifier
    type: FieldType
    required: bool = False
    description: ShortText | None = None
    enum_values: list[ShortText] = Field(default_factory=list)
    reference_entity_id: Identifier | None = None

    @model_validator(mode="after")
    def _type_specific(self) -> Self:
        if self.type is FieldType.ENUM and not self.enum_values:
            raise ValueError(f"enum field '{self.name}' must list enum_values")
        if self.type is not FieldType.ENUM and self.enum_values:
            raise ValueError(f"only enum fields may list enum_values (field '{self.name}')")
        if self.type is FieldType.REFERENCE and self.reference_entity_id is None:
            raise ValueError(f"reference field '{self.name}' must set reference_entity_id")
        return self


class Relationship(StrictModel):
    target_entity_id: Identifier
    kind: Literal["one-to-one", "one-to-many", "many-to-one", "many-to-many"]
    description: ShortText | None = None


class DataEntity(TrackedItem):
    name: ShortText
    description: LongText | None = None
    fields: list[EntityField] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class IntegrationContract(TrackedItem):
    name: ShortText
    kind: Literal["rest", "graphql", "file", "event", "database", "other"]
    direction: Literal["inbound", "outbound", "bidirectional"]
    description: LongText | None = None
    entity_ids: list[Identifier] = Field(default_factory=list)


class AuthorizationRule(TrackedItem):
    role_id: Identifier
    resource: ShortText
    actions: list[Literal["create", "read", "update", "delete", "approve", "execute", "export"]] = Field(min_length=1)
    condition: ShortText | None = None


class NavigationItem(StrictModel):
    id: Identifier
    label: ShortText
    screen_id: Identifier | None = None
    children: list[NavigationItem] = Field(default_factory=list)


class ValidationRule(StrictModel):
    kind: Literal["required", "min", "max", "min-length", "max-length", "pattern", "custom"]
    value: str | float | None = None
    message: ShortText | None = None


class FormField(StrictModel):
    name: Identifier
    label: ShortText
    type: FieldType
    required: bool = False
    help_text: ShortText | None = None
    validation: list[ValidationRule] = Field(default_factory=list)


class ComponentSpec(StrictModel):
    """Semantic component intent; mapped to design-system components later."""

    id: Identifier
    kind: Literal[
        "form", "table", "card", "metric", "chart", "dialog", "tabs", "list", "toolbar", "notification", "text", "other"
    ]
    label: ShortText | None = None
    entity_id: Identifier | None = None


class Screen(TrackedItem):
    name: ShortText
    purpose: LongText | None = None
    persona_ids: list[Identifier] = Field(default_factory=list)
    requirement_ids: list[Identifier] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    fields: list[FormField] = Field(default_factory=list)
    states: list[UiState] = Field(default_factory=list)


class AccessibilityRequirements(StrictModel):
    standard: Tracked[Literal["WCAG 2.1 AA", "WCAG 2.2 AA", "WCAG 2.2 AAA"]] = Field(default_factory=Tracked)
    notes: list[ShortText] = Field(default_factory=list)


class ResponsiveRule(TrackedItem):
    breakpoint: Literal["mobile", "tablet", "desktop", "wide"]
    behavior: LongText


class DesignSystemSelection(StrictModel):
    id: Tracked[Identifier] = Field(default_factory=Tracked)
    version: Tracked[ShortText] = Field(default_factory=Tracked)


class FrameworkConfig(StrictModel):
    framework: Tracked[Framework] = Field(default_factory=Tracked)
    language: Literal["typescript"] = "typescript"


class DesignConstraint(TrackedItem):
    statement: LongText


class SecurityProfile(StrictModel):
    classification: Tracked[Classification] = Field(default_factory=Tracked)
    risk_level: Tracked[RiskLevel] = Field(default_factory=Tracked)


class Assumption(TrackedItem):
    statement: LongText
    related_ids: list[Identifier] = Field(default_factory=list)


class OpenQuestion(StrictModel):
    id: Identifier
    question: LongText
    blocking: bool = False
    related_ids: list[Identifier] = Field(default_factory=list)


class Decision(TrackedItem):
    summary: ShortText
    rationale: LongText | None = None
    related_ids: list[Identifier] = Field(default_factory=list)


class ArtifactDependency(StrictModel):
    from_id: Identifier
    to_id: Identifier
    kind: Literal["derives-from", "implements", "constrains", "tests"] = "derives-from"


# --------------------------------------------------------------------------- root

#: Collections whose items share one identifier namespace across the spec.
ID_COLLECTIONS: tuple[str, ...] = (
    "personas",
    "roles",
    "journeys",
    "functional_requirements",
    "nonfunctional_requirements",
    "acceptance_criteria",
    "business_rules",
    "entities",
    "integrations",
    "authorization",
    "screens",
    "responsive",
    "org_constraints",
    "assumptions",
    "open_questions",
    "decisions",
)


class ApplicationSpec(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    metadata: ProjectMetadata
    objective: Tracked[LongText] = Field(default_factory=Tracked)
    domain: Tracked[ShortText] = Field(default_factory=Tracked)
    personas: list[Persona] = Field(default_factory=list)
    roles: list[Role] = Field(default_factory=list)
    journeys: list[UserJourney] = Field(default_factory=list)
    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)
    nonfunctional_requirements: list[NonFunctionalRequirement] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    business_rules: list[BusinessRule] = Field(default_factory=list)
    entities: list[DataEntity] = Field(default_factory=list)
    integrations: list[IntegrationContract] = Field(default_factory=list)
    authorization: list[AuthorizationRule] = Field(default_factory=list)
    navigation: list[NavigationItem] = Field(default_factory=list)
    screens: list[Screen] = Field(default_factory=list)
    accessibility: AccessibilityRequirements = Field(default_factory=AccessibilityRequirements)
    responsive: list[ResponsiveRule] = Field(default_factory=list)
    design_system: DesignSystemSelection = Field(default_factory=DesignSystemSelection)
    framework: FrameworkConfig = Field(default_factory=FrameworkConfig)
    org_constraints: list[DesignConstraint] = Field(default_factory=list)
    security: SecurityProfile = Field(default_factory=SecurityProfile)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    artifact_dependencies: list[ArtifactDependency] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        seen: dict[str, str] = {}
        for collection in ID_COLLECTIONS:
            for item in getattr(self, collection):
                if item.id in seen:
                    raise ValueError(f"duplicate id '{item.id}' in '{collection}' (already used in '{seen[item.id]}')")
                seen[item.id] = collection
        nav_ids: set[str] = set()
        stack = list(self.navigation)
        while stack:
            node = stack.pop()
            if node.id in nav_ids:
                raise ValueError(f"duplicate navigation id '{node.id}'")
            nav_ids.add(node.id)
            stack.extend(node.children)
        return self

    @classmethod
    def empty(cls, name: str, description: str | None = None) -> ApplicationSpec:
        """A new project's spec: only metadata is known; everything else is explicitly unknown."""
        return cls(metadata=ProjectMetadata(name=name, description=description))


NavigationItem.model_rebuild()
