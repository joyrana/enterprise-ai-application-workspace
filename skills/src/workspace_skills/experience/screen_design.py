"""screen-design: propose the screens a specification still needs.

The model proposes screens as a small schema (:class:`ScreensAnswer`).
Deterministic code then:

* keeps only references to requirements, personas and entities that exist (an
  unknown entity id is removed, so the component becomes a placeholder in the UI
  IR rather than a dangling reference);
* skips screens whose name duplicates an existing one, and screens without
  components;
* allocates screen and component ids and caps list sizes.

Accepted proposals become ``spec.screens`` items, from which the UI IR is derived
(ADR-0013), so every screen a model suggests is reviewed before it reaches the
design preview.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from appspec import ApplicationSpec
from appspec.model import ID_COLLECTIONS, DataEntity
from model_gateway import Message, generate_structured
from skill_sdk import AddItem, Category, IdAllocator, SkillContext, SkillManifest, SkillOutput
from workspace_skills.common import (
    confirmed_context,
    load_prompt,
    model_info,
    norm,
    read_message,
    require_provider,
    summarize,
    wrap_user_text,
)

PROMPT_VERSION = "screen-design@1"
MAX_SCREENS = 6
MAX_COMPONENTS = 5

ComponentKind = Literal[
    "form", "table", "card", "metric", "chart", "dialog", "tabs", "list", "toolbar", "notification", "text", "other"
]
StateName = Literal["loading", "empty", "error", "success", "disabled"]


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ComponentProposal(_Answer):
    kind: ComponentKind
    label: str | None = Field(default=None, max_length=200)
    entity_id: str | None = Field(default=None, max_length=64)


class ScreenProposal(_Answer):
    name: str = Field(min_length=1, max_length=200)
    purpose: str | None = Field(default=None, max_length=1000)
    requirement_ids: list[str] = Field(default_factory=list, max_length=20)
    persona_ids: list[str] = Field(default_factory=list, max_length=10)
    components: list[ComponentProposal] = Field(default_factory=list, max_length=12)
    states: list[StateName] = Field(default_factory=list, max_length=5)

    @field_validator("components", mode="before")
    @classmethod
    def _cap(cls, value: object) -> object:
        return value[:12] if isinstance(value, list) else value


class ScreensAnswer(_Answer):
    screens: list[ScreenProposal] = Field(default_factory=list, max_length=12)

    @field_validator("screens", mode="before")
    @classmethod
    def _cap(cls, value: object) -> object:
        return value[:12] if isinstance(value, list) else value


def _entity_line(entity: DataEntity) -> str:
    fields = ", ".join(f"{f.name} ({f.type.value})" for f in entity.fields) or "none"
    return f'- id: {entity.id} | name: "{entity.name}" | fields: {fields}'


def build_messages(spec: ApplicationSpec, message: str) -> list[Message]:
    reqs = "\n".join(
        f'- id: {r.id} | title: "{r.title}" | priority: {r.priority.value}' for r in spec.functional_requirements
    )
    personas = "\n".join(f'- id: {p.id} | name: "{p.name}"' for p in spec.personas) or "- (none yet)"
    entities = "\n".join(_entity_line(e) for e in spec.entities) or "- (none yet)"
    existing = "\n".join(f'- "{s.name}"' for s in spec.screens) or "- (none yet)"
    user = (
        f"Confirmed context:\n{confirmed_context(spec)}\n\n"
        f"<requirements>\n{reqs}\n</requirements>\n\n"
        f"<personas>\n{personas}\n</personas>\n\n"
        f"<entities>\n{entities}\n</entities>\n\n"
        f"<existing_screens>\n{existing}\n</existing_screens>\n\n"
        f"{wrap_user_text(message or 'Propose the screens this application needs.')}"
    )
    system = load_prompt(__package__ or "workspace_skills.experience", "screen_design_v1.md")
    return [Message(role="system", content=system), Message(role="user", content=user)]


def to_proposals(spec: ApplicationSpec, answer: ScreensAnswer) -> list[AddItem]:
    requirement_ids = {r.id for r in spec.functional_requirements}
    persona_ids = {p.id for p in spec.personas}
    entity_ids = {e.id for e in spec.entities}
    existing_names = {norm(s.name) for s in spec.screens}
    taken = {item.id for name in ID_COLLECTIONS for item in getattr(spec, name)}
    ids = IdAllocator(taken)
    proposal_ids = IdAllocator(())
    proposals: list[AddItem] = []
    for screen in answer.screens:
        if len(proposals) >= MAX_SCREENS:
            break
        key = norm(screen.name)
        if not key or key in existing_names or not screen.components:
            continue
        existing_names.add(key)
        screen_id = ids.allocate(screen.name, fallback="screen")
        component_ids = IdAllocator(())
        components: list[dict[str, Any]] = []
        for component in screen.components[:MAX_COMPONENTS]:
            item: dict[str, Any] = {
                "id": component_ids.allocate(component.label or component.kind, fallback=component.kind),
                "kind": component.kind,
            }
            if component.label and component.label.strip():
                item["label"] = component.label.strip()
            if component.entity_id in entity_ids:
                item["entity_id"] = component.entity_id
            components.append(item)
        screen_item: dict[str, Any] = {
            "id": screen_id,
            "name": screen.name.strip(),
            "requirement_ids": list(dict.fromkeys(r for r in screen.requirement_ids if r in requirement_ids)),
            "persona_ids": list(dict.fromkeys(p for p in screen.persona_ids if p in persona_ids)),
            "components": components,
            "states": list(dict.fromkeys(screen.states)),
        }
        if screen.purpose and screen.purpose.strip():
            screen_item["purpose"] = screen.purpose.strip()
        proposals.append(
            AddItem(proposal_id=proposal_ids.allocate(f"p-{screen_id}"), collection="screens", item=screen_item)
        )
    return proposals


def uncovered_requirements(spec: ApplicationSpec, proposals: list[AddItem]) -> list[str]:
    """Requirement ids no existing or proposed screen serves (reported in the summary)."""
    served = {rid for s in spec.screens for rid in s.requirement_ids}
    served |= {rid for p in proposals for rid in p.item.get("requirement_ids", [])}
    return [r.id for r in spec.functional_requirements if r.id not in served]


class ScreenDesign:
    manifest: ClassVar[SkillManifest] = SkillManifest(
        id="screen-design",
        name="Screen design",
        description=(
            "Proposes the screens the application still needs, each linked to the requirements it serves, "
            "the personas who use it and the data entities its forms and tables show."
        ),
        version="0.1.0",
        category=Category.EXPERIENCE_DESIGN,
        intents=(
            "design the screens",
            "what pages does the app need",
            "propose the user interface",
            "screen layout for these requirements",
        ),
        optional_inputs=("message",),
        preconditions=("/functional_requirements",),
        max_model_calls=2,
        max_total_tokens=40_000,
        prompt_version=PROMPT_VERSION,
        completion_criteria="Screens were proposed for requirements without one, or every requirement has a screen.",
        failure_behavior="On provider or schema failure no proposals are returned; the specification is unchanged.",
        eval_suites=("routing", "screens"),
    )

    def run(self, context: SkillContext, inputs: dict[str, Any]) -> SkillOutput:
        message = read_message(inputs, required=False)
        spec = context.spec
        if not uncovered_requirements(spec, []) and not message:
            return SkillOutput(
                summary="Every functional requirement already has a screen.",
                proposals=[],
                not_applicable_reason="Every functional requirement already has a screen.",
            )
        result = generate_structured(
            require_provider(context),
            build_messages(spec, message),
            ScreensAnswer,
            budget=context.budget,
            max_repairs=self.manifest.retry.max_repairs,
            call_timeout_s=context.call_timeout_s,
            prices=context.prices,
        )
        proposals = to_proposals(spec, result.value)
        summary = summarize(list(proposals))
        uncovered = uncovered_requirements(spec, proposals)
        if uncovered:
            summary += f" Requirements still without a screen: {', '.join(uncovered)}."
        return SkillOutput(summary=summary, proposals=list(proposals), model=model_info(result, PROMPT_VERSION))
