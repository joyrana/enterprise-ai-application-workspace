"""requirements-conflict-detection: surface contradictions as blocking open questions.

Two layers:

* Deterministic: near-duplicate requirement titles (token Jaccard ≥ 0.8) are
  reported without a model.
* Model: semantic contradictions between requirements, business rules and
  non-functional requirements. A model-reported conflict counts only if it
  cites at least two distinct, existing element ids.

Output is always open questions (blocking, with ``related_ids``) — this skill
never edits requirements itself.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from appspec import ApplicationSpec
from model_gateway import Message, generate_structured
from skill_sdk import AddOpenQuestion, Category, IdAllocator, SkillContext, SkillManifest, SkillOutput
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

PROMPT_VERSION = "conflict-detection@2"  # @2: security note after flagged requests
MAX_CONFLICTS = 8
DUPLICATE_THRESHOLD = 0.8
_WORD = re.compile(r"[a-z0-9]+")


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConflictProposal(_Answer):
    element_ids: list[str] = Field(min_length=2, max_length=6)
    explanation: str = Field(min_length=5, max_length=500)
    question: str = Field(min_length=5, max_length=500)


class ConflictAnswer(_Answer):
    conflicts: list[ConflictProposal] = Field(default_factory=list, max_length=20)

    @field_validator("conflicts", mode="before")
    @classmethod
    def _truncate(cls, value: object) -> object:
        return value[:20] if isinstance(value, list) else value


def elements(spec: ApplicationSpec) -> list[tuple[str, str, str]]:
    """(id, kind, text) for every element the model may cite."""
    out: list[tuple[str, str, str]] = []
    for r in spec.functional_requirements:
        out.append((r.id, "requirement", r.title + (f" — {r.description}" if r.description else "")))
    for b in spec.business_rules:
        out.append((b.id, "business rule", b.statement))
    for n in spec.nonfunctional_requirements:
        out.append((n.id, f"non-functional ({n.category.value})", n.statement))
    return out


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def near_duplicates(spec: ApplicationSpec) -> list[tuple[str, str]]:
    pairs = []
    for a, b in combinations(spec.functional_requirements, 2):
        ta, tb = _tokens(a.title), _tokens(b.title)
        if ta and tb and len(ta & tb) / len(ta | tb) >= DUPLICATE_THRESHOLD:
            pairs.append((a.id, b.id))
    return pairs


def build_messages(spec: ApplicationSpec, message: str) -> list[Message]:
    listed = "\n".join(f"- id: {i} | {kind}: {text}" for i, kind, text in elements(spec))
    user = (
        f"Confirmed context:\n{confirmed_context(spec)}\n\n<elements>\n{listed}\n</elements>\n\n"
        f"{wrap_user_text(message or 'Check these requirements for conflicts.')}"
    )
    system = load_prompt(__package__ or "workspace_skills.discovery", "conflict_detection_v1.md")
    return [Message(role="system", content=system), Message(role="user", content=user)]


def to_proposals(
    spec: ApplicationSpec, duplicates: list[tuple[str, str]], answer: ConflictAnswer | None
) -> list[AddOpenQuestion]:
    known = {i for i, _, _ in elements(spec)}
    titles = {r.id: r.title for r in spec.functional_requirements}
    taken = {q.id for q in spec.open_questions} | known
    ids = IdAllocator(taken)
    proposal_ids = IdAllocator(())
    existing_questions = {norm(q.question) for q in spec.open_questions}
    seen_sets: set[frozenset[str]] = set()
    proposals: list[AddOpenQuestion] = []

    def add(related: list[str], question: str) -> None:
        key = frozenset(related)
        if key in seen_sets or norm(question) in existing_questions or len(proposals) >= MAX_CONFLICTS:
            return
        seen_sets.add(key)
        existing_questions.add(norm(question))
        qid = ids.allocate("conflict-" + "-".join(sorted(related))[:40], prefix="q")
        proposals.append(
            AddOpenQuestion(
                proposal_id=proposal_ids.allocate(f"p-{qid}"),
                question_id=qid,
                question=question,
                blocking=True,
                related_ids=sorted(related),
            )
        )

    for a, b in duplicates:
        add([a, b], f'"{titles[a]}" and "{titles[b]}" look like the same requirement. Should they be merged?')
    if answer is not None:
        for c in answer.conflicts:
            related = list(dict.fromkeys(i for i in c.element_ids if i in known))
            if len(related) < 2:
                continue  # a conflict must cite at least two real elements
            add(related, f"{c.question.strip()} (Conflict: {c.explanation.strip()})"[:1000])
    return proposals


class ConflictDetection:
    manifest: ClassVar[SkillManifest] = SkillManifest(
        id="requirements-conflict-detection",
        name="Conflict check",
        description=(
            "Finds contradictory or duplicate requirements and business rules and raises each as a "
            "blocking open question linked to the elements involved."
        ),
        version="0.1.0",
        category=Category.DISCOVERY,
        intents=(
            "check requirements for conflicts",
            "find contradictions",
            "are any requirements inconsistent",
            "duplicate requirements",
        ),
        optional_inputs=("message",),
        preconditions=("/functional_requirements",),
        max_model_calls=2,
        max_total_tokens=40_000,
        prompt_version=PROMPT_VERSION,
        completion_criteria="Conflicts were raised as open questions, or none were found.",
        failure_behavior="On provider or schema failure no proposals are returned; the specification is unchanged.",
        eval_suites=("routing",),
    )

    def run(self, context: SkillContext, inputs: dict[str, Any]) -> SkillOutput:
        message = read_message(inputs, required=False)
        spec = context.spec
        duplicates = near_duplicates(spec)
        if len(elements(spec)) < 2:
            return SkillOutput(
                summary="At least two requirements or rules are needed to check for conflicts.",
                proposals=[],
                not_applicable_reason="At least two requirements or rules are needed to check for conflicts.",
            )
        result = generate_structured(
            require_provider(context),
            build_messages(spec, message),
            ConflictAnswer,
            budget=context.budget,
            max_repairs=self.manifest.retry.max_repairs,
            call_timeout_s=context.call_timeout_s,
            prices=context.prices,
        )
        proposals = to_proposals(spec, duplicates, result.value)
        summary = summarize(list(proposals)) if proposals else "No conflicts found."
        return SkillOutput(summary=summary, proposals=list(proposals), model=model_info(result, PROMPT_VERSION))
