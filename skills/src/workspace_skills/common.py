"""Helpers shared by built-in skills."""

from __future__ import annotations

from importlib import resources
from typing import Any

from appspec import ApplicationSpec, FactStatus
from model_gateway import ErrorKind, ModelError, ModelProvider, StructuredResult
from skill_sdk import AddItem, AddOpenQuestion, SetFact, SkillContext, scan_text, untrusted_notice

MAX_MESSAGE_CHARS = 8000


def read_message(inputs: dict[str, Any], *, required: bool) -> str:
    """The user's request text. ``description`` is accepted for runs created before 2b."""
    message = str(inputs.get("message") or inputs.get("description") or "").strip()
    if required and not message:
        raise ValueError("message is required")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message must be at most {MAX_MESSAGE_CHARS} characters")
    return message


def require_provider(context: SkillContext) -> ModelProvider:
    if context.provider is None:
        raise ModelError(ErrorKind.NOT_CONFIGURED)
    return context.provider


def load_prompt(package: str, name: str) -> str:
    return resources.files(package).joinpath(f"prompts/{name}").read_text(encoding="utf-8")


def model_info(result: StructuredResult[Any], prompt_version: str) -> dict[str, Any]:
    """Telemetry for a run record. Never includes prompt or completion text."""
    return {
        "model_id": result.model_id,
        "profile": result.profile,
        "prompt_version": prompt_version,
        "usage": result.usage.model_dump() | {"total_tokens": result.usage.total_tokens},
        "repaired": result.repaired,
        "estimated_cost_usd": result.estimated_cost_usd,
        "calls": [c.model_dump() for c in result.calls],
    }


def summarize(proposals: list[SetFact | AddItem | AddOpenQuestion]) -> str:
    kinds = {"set_fact": 0, "add_item": 0, "add_open_question": 0}
    for proposal in proposals:
        kinds[proposal.op] += 1
    return (
        f"{len(proposals)} proposal(s): {kinds['set_fact']} fact(s), {kinds['add_item']} item(s), "
        f"{kinds['add_open_question']} open question(s)."
    )


def wrap_user_text(text: str, tag: str = "user_message") -> str:
    """Delimit untrusted user text; a closing delimiter inside it cannot end the block.

    When the deterministic scan finds instruction-like content, a security note
    follows the block so the model is told, outside the data, to treat it as data.
    """
    safe = text.replace(f"</{tag}>", f"</ {tag}>")
    block = f"<{tag}>\n{safe}\n</{tag}>"
    notice = untrusted_notice(scan_text(text))
    return f"{block}\n\n{notice}" if notice else block


def confirmed_context(spec: ApplicationSpec) -> str:
    lines = [f"- Application name: {spec.metadata.name}"]
    for label, fact in (("Objective", spec.objective), ("Domain", spec.domain)):
        if fact.status is FactStatus.CONFIRMED:
            lines.append(f"- {label}: {fact.value}")
    return "\n".join(lines)


def norm(text: str) -> str:
    return " ".join(text.lower().split())
