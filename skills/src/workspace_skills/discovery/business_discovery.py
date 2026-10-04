"""business-discovery: free-text intent → proposed objective, domain, personas, requirements, questions.

The model returns a small, model-friendly schema (:class:`DiscoveryAnswer`).
Deterministic code then converts it into typed spec commands with stable ids,
resolves persona references, drops anything already settled in the spec, and
caps list sizes. The model never produces spec commands or ids itself.
"""

from __future__ import annotations

from importlib import resources
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from appspec import ApplicationSpec, FactStatus
from appspec.model import ID_COLLECTIONS
from model_gateway import ErrorKind, Message, ModelError, generate_structured
from skill_sdk import (
    AddItem,
    AddOpenQuestion,
    Category,
    IdAllocator,
    SetFact,
    SkillContext,
    SkillManifest,
    SkillOutput,
)

PROMPT_VERSION = "business-discovery@1"
MAX_DESCRIPTION_CHARS = 8000


class _Answer(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PersonaProposal(_Answer):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    goals: list[str] = Field(default_factory=list, max_length=6)


class RequirementProposal(_Answer):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: Literal["must", "should", "could"] = "should"
    persona_names: list[str] = Field(default_factory=list, max_length=6)


class QuestionProposal(_Answer):
    question: str = Field(min_length=5, max_length=1000)
    blocking: bool = False


class DiscoveryAnswer(_Answer):
    """What the model is asked to return."""

    is_application_request: bool
    not_applicable_reason: str | None = Field(default=None, max_length=500)
    application_type: str | None = Field(default=None, max_length=120)
    domain: str | None = Field(default=None, max_length=120)
    objective: str | None = Field(default=None, max_length=1000)
    personas: list[PersonaProposal] = Field(default_factory=list, max_length=8)
    requirements: list[RequirementProposal] = Field(default_factory=list, max_length=15)
    open_questions: list[QuestionProposal] = Field(default_factory=list, max_length=10)
    assumptions: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("personas", "requirements", "open_questions", "assumptions", mode="before")
    @classmethod
    def _truncate(cls, value: object, info: Any) -> object:
        """Over-long lists are truncated rather than spending a repair call on them."""
        caps = {"personas": 8, "requirements": 15, "open_questions": 10, "assumptions": 8}
        if isinstance(value, list):
            return value[: caps[info.field_name]]
        return value


LIMITS = {"personas": 6, "requirements": 12, "open_questions": 8, "assumptions": 6}


def _known_facts(spec: ApplicationSpec) -> list[str]:
    lines = [f"- Application name: {spec.metadata.name}"]
    for label, fact in (("Objective", spec.objective), ("Domain", spec.domain)):
        if fact.status is FactStatus.CONFIRMED:
            lines.append(f"- {label}: {fact.value}")
    for persona in spec.personas:
        if persona.status == "confirmed":
            lines.append(f"- Persona: {persona.name}")
    for requirement in spec.functional_requirements:
        if requirement.status == "confirmed":
            lines.append(f"- Requirement: {requirement.title}")
    return lines


def build_messages(spec: ApplicationSpec, description: str) -> list[Message]:
    system = resources.files(__package__).joinpath("prompts/business_discovery_v1.md").read_text(encoding="utf-8")
    known = "\n".join(_known_facts(spec))
    # Neutralise attempts to close the data delimiter from inside the description.
    safe = description.replace("</user_description>", "</ user_description>")
    user = (
        f"Already known (do not ask about these):\n{known}\n\n"
        f"<user_description>\n{safe}\n</user_description>\n\n"
        "Propose the structured understanding now."
    )
    return [Message(role="system", content=system), Message(role="user", content=user)]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def to_proposals(spec: ApplicationSpec, answer: DiscoveryAnswer) -> list[SetFact | AddItem | AddOpenQuestion]:
    """Deterministically convert the model's answer into typed, de-duplicated spec commands."""
    if not answer.is_application_request:
        return []
    taken = {item.id for name in ID_COLLECTIONS for item in getattr(spec, name)}
    ids = IdAllocator(taken)
    proposal_ids = IdAllocator(())
    proposals: list[SetFact | AddItem | AddOpenQuestion] = []

    for path, value in (("/objective", answer.objective), ("/domain", answer.domain)):
        fact = spec.objective if path == "/objective" else spec.domain
        if value and value.strip() and fact.status is not FactStatus.CONFIRMED:
            proposals.append(
                SetFact(proposal_id=proposal_ids.allocate(f"p-{path.strip('/')}"), path=path, value=value.strip())  # type: ignore[arg-type]
            )

    existing_personas = {_norm(p.name): p.id for p in spec.personas}
    persona_ids: dict[str, str] = dict(existing_personas)
    for persona in answer.personas[: LIMITS["personas"]]:
        key = _norm(persona.name)
        if key in persona_ids:
            continue
        persona_id = ids.allocate(persona.name, fallback="persona")
        persona_ids[key] = persona_id
        item: dict[str, Any] = {"id": persona_id, "name": persona.name.strip(), "goals": persona.goals[:6]}
        if persona.description:
            item["description"] = persona.description.strip()
        proposals.append(
            AddItem(proposal_id=proposal_ids.allocate(f"p-{persona_id}"), collection="personas", item=item)
        )

    existing_requirements = {_norm(r.title) for r in spec.functional_requirements}
    for requirement in answer.requirements[: LIMITS["requirements"]]:
        if _norm(requirement.title) in existing_requirements:
            continue
        existing_requirements.add(_norm(requirement.title))
        requirement_id = ids.allocate(requirement.title, fallback="req")
        linked = [persona_ids[_norm(n)] for n in requirement.persona_names if _norm(n) in persona_ids]
        item = {
            "id": requirement_id,
            "title": requirement.title.strip(),
            "priority": requirement.priority,
            "persona_ids": list(dict.fromkeys(linked)),
        }
        if requirement.description:
            item["description"] = requirement.description.strip()
        proposals.append(
            AddItem(
                proposal_id=proposal_ids.allocate(f"p-{requirement_id}"),
                collection="functional_requirements",
                item=item,
            )
        )

    existing_assumptions = {_norm(a.statement) for a in spec.assumptions}
    for statement in answer.assumptions[: LIMITS["assumptions"]]:
        if not statement.strip() or _norm(statement) in existing_assumptions:
            continue
        existing_assumptions.add(_norm(statement))
        assumption_id = ids.allocate(statement, prefix="assume", fallback="assume")
        proposals.append(
            AddItem(
                proposal_id=proposal_ids.allocate(f"p-{assumption_id}"),
                collection="assumptions",
                item={"id": assumption_id, "statement": statement.strip()},
            )
        )

    existing_questions = {_norm(q.question) for q in spec.open_questions}
    for question in answer.open_questions[: LIMITS["open_questions"]]:
        if _norm(question.question) in existing_questions:
            continue
        existing_questions.add(_norm(question.question))
        question_id = ids.allocate(question.question, prefix="q", fallback="q")
        proposals.append(
            AddOpenQuestion(
                proposal_id=proposal_ids.allocate(f"p-{question_id}"),
                question_id=question_id,
                question=question.question.strip(),
                blocking=question.blocking,
            )
        )
    return proposals


class BusinessDiscovery:
    manifest: ClassVar[SkillManifest] = SkillManifest(
        id="business-discovery",
        name="Business discovery",
        description=(
            "Turns a free-text description of a desired application into proposed objective, domain, "
            "personas, functional requirements, assumptions and the smallest useful set of open questions."
        ),
        version="0.1.0",
        category=Category.DISCOVERY,
        intents=("describe an application", "start a new application", "what should we build"),
        required_inputs=("description",),
        max_model_calls=2,
        max_total_tokens=40_000,
        timeout_s=180,
        prompt_version=PROMPT_VERSION,
        completion_criteria=(
            "A validated DiscoveryAnswer was produced and converted into proposals, or the input was "
            "classified as not an application request."
        ),
        failure_behavior=(
            "On provider or schema failure, no proposals are returned and the classified error is reported; "
            "the specification is never changed by this skill."
        ),
        eval_suites=("discovery",),
    )

    def run(self, context: SkillContext, inputs: dict[str, Any]) -> SkillOutput:
        description = str(inputs.get("description", "")).strip()
        if not description:
            raise ValueError("description is required")
        if len(description) > MAX_DESCRIPTION_CHARS:
            raise ValueError(f"description must be at most {MAX_DESCRIPTION_CHARS} characters")
        if context.provider is None:
            raise ModelError(ErrorKind.NOT_CONFIGURED)

        result = generate_structured(
            context.provider,
            build_messages(context.spec, description),
            DiscoveryAnswer,
            budget=context.budget,
            max_repairs=self.manifest.retry.max_repairs,
            call_timeout_s=context.call_timeout_s,
            prices=context.prices,
        )
        answer = result.value
        proposals = to_proposals(context.spec, answer)
        model_info = {
            "model_id": result.model_id,
            "profile": result.profile,
            "prompt_version": PROMPT_VERSION,
            "usage": result.usage.model_dump() | {"total_tokens": result.usage.total_tokens},
            "repaired": result.repaired,
            "estimated_cost_usd": result.estimated_cost_usd,
            "calls": [c.model_dump() for c in result.calls],
        }
        if not answer.is_application_request:
            return SkillOutput(
                summary="The description does not look like a request to build an application.",
                proposals=[],
                not_applicable_reason=answer.not_applicable_reason or "Not an application request.",
                model=model_info,
            )
        kinds = {"set_fact": 0, "add_item": 0, "add_open_question": 0}
        for proposal in proposals:
            kinds[proposal.op] += 1
        summary = (
            f"{len(proposals)} proposal(s): {kinds['set_fact']} fact(s), {kinds['add_item']} item(s), "
            f"{kinds['add_open_question']} open question(s)."
        )
        return SkillOutput(summary=summary, proposals=proposals, model=model_info)
