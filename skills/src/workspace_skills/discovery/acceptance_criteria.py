"""acceptance-criteria: propose Given/When/Then criteria for requirements that lack them.

Deterministic parts: which requirements are targeted (those without criteria,
optionally narrowed by the message), id validation, id allocation, caps and
de-duplication. When nothing needs criteria, the skill returns without calling
a model.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from appspec import ApplicationSpec
from appspec.model import ID_COLLECTIONS, FunctionalRequirement
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

PROMPT_VERSION = "acceptance-criteria@1"
MAX_TARGETS = 6
MAX_PER_REQUIREMENT = 3
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with", "acceptance", "criteria", "write"}


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CriterionProposal(_Answer):
    requirement_id: str = Field(min_length=1, max_length=64)
    given: str = Field(min_length=3, max_length=500)
    when: str = Field(min_length=3, max_length=500)
    then: str = Field(min_length=3, max_length=500)


class CriteriaAnswer(_Answer):
    criteria: list[CriterionProposal] = Field(default_factory=list, max_length=30)

    @field_validator("criteria", mode="before")
    @classmethod
    def _truncate(cls, value: object) -> object:
        return value[:30] if isinstance(value, list) else value


def select_targets(spec: ApplicationSpec, message: str) -> list[FunctionalRequirement]:
    """Requirements without criteria; if the message names some, those come first (and only those)."""
    covered = {ac.requirement_id for ac in spec.acceptance_criteria}
    open_reqs = [r for r in spec.functional_requirements if r.id not in covered]
    words = set(_WORD.findall(message.lower()))
    if words:
        named = [
            r for r in open_reqs if r.id in message or len((words - _STOP) & set(_WORD.findall(r.title.lower()))) >= 2
        ]
        if named:
            return named[:MAX_TARGETS]
    return open_reqs[:MAX_TARGETS]


def build_messages(spec: ApplicationSpec, targets: list[FunctionalRequirement], message: str) -> list[Message]:
    lines = []
    for r in targets:
        line = f'- id: {r.id} | title: "{r.title}" | priority: {r.priority.value}'
        if r.description:
            line += f" | description: {r.description}"
        lines.append(line)
    user = (
        f"Confirmed context:\n{confirmed_context(spec)}\n\n"
        f"<requirements>\n{chr(10).join(lines)}\n</requirements>\n\n"
        f"{wrap_user_text(message or 'Write acceptance criteria for these requirements.')}"
    )
    system = load_prompt(__package__ or "workspace_skills.discovery", "acceptance_criteria_v1.md")
    return [Message(role="system", content=system), Message(role="user", content=user)]


def to_proposals(spec: ApplicationSpec, targets: list[FunctionalRequirement], answer: CriteriaAnswer) -> list[AddItem]:
    target_ids = {r.id for r in targets}
    taken = {item.id for name in ID_COLLECTIONS for item in getattr(spec, name)}
    ids = IdAllocator(taken)
    proposal_ids = IdAllocator(())
    seen: set[tuple[str, str]] = set()
    per_requirement: dict[str, int] = {}
    proposals: list[AddItem] = []
    for c in answer.criteria:
        if c.requirement_id not in target_ids:
            continue  # the model may only reference the requirements it was given
        key = (c.requirement_id, norm(f"{c.given} {c.when} {c.then}"))
        if key in seen or per_requirement.get(c.requirement_id, 0) >= MAX_PER_REQUIREMENT:
            continue
        seen.add(key)
        per_requirement[c.requirement_id] = per_requirement.get(c.requirement_id, 0) + 1
        ac_id = ids.allocate(f"{c.requirement_id}-{per_requirement[c.requirement_id]}", prefix="ac")
        proposals.append(
            AddItem(
                proposal_id=proposal_ids.allocate(f"p-{ac_id}"),
                collection="acceptance_criteria",
                item={
                    "id": ac_id,
                    "requirement_id": c.requirement_id,
                    "given": c.given.strip(),
                    "when": c.when.strip(),
                    "then": c.then.strip(),
                },
            )
        )
    return proposals


class AcceptanceCriteria:
    manifest: ClassVar[SkillManifest] = SkillManifest(
        id="acceptance-criteria",
        name="Acceptance criteria",
        description=(
            "Proposes testable Given/When/Then acceptance criteria for functional requirements that "
            "do not have any yet."
        ),
        version="0.1.0",
        category=Category.DISCOVERY,
        intents=(
            "write acceptance criteria",
            "how do we test this requirement",
            "define done for requirements",
            "given when then scenarios",
        ),
        optional_inputs=("message",),
        preconditions=("/functional_requirements",),
        max_model_calls=2,
        max_total_tokens=40_000,
        prompt_version=PROMPT_VERSION,
        completion_criteria="Criteria were proposed for the targeted requirements, or none needed them.",
        failure_behavior="On provider or schema failure no proposals are returned; the specification is unchanged.",
        eval_suites=("routing",),
    )

    def run(self, context: SkillContext, inputs: dict[str, Any]) -> SkillOutput:
        message = read_message(inputs, required=False)
        targets = select_targets(context.spec, message)
        if not targets:
            return SkillOutput(
                summary="Every functional requirement already has acceptance criteria.",
                proposals=[],
                not_applicable_reason="Every functional requirement already has acceptance criteria.",
            )
        provider = require_provider(context)
        result = generate_structured(
            provider,
            build_messages(context.spec, targets, message),
            CriteriaAnswer,
            budget=context.budget,
            max_repairs=self.manifest.retry.max_repairs,
            call_timeout_s=context.call_timeout_s,
            prices=context.prices,
        )
        proposals = to_proposals(context.spec, targets, result.value)
        return SkillOutput(
            summary=summarize(list(proposals)), proposals=list(proposals), model=model_info(result, PROMPT_VERSION)
        )
