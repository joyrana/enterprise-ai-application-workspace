"""Two-stage skill routing.

Stage 1 (deterministic, no model): keep the latest version of every skill whose
preconditions the specification satisfies.

Stage 2:
* an explicitly requested skill is validated and used;
* zero candidates → no skill; one candidate → that skill (no model call — a
  deterministic lookup must not cost a model call);
* several candidates → the model chooses one of them, or ``none``, through a
  schema whose ``skill_id`` is constrained to the candidate ids.

:func:`lexical_choice` is a simple keyword baseline used only for evaluation
comparisons. It is never a silent fallback when the model fails.
"""

from __future__ import annotations

import re
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from appspec import ApplicationSpec
from model_gateway import Budget, ErrorKind, Message, ModelError, ModelProvider, Prices, generate_structured

from .registry import RegistryError, SkillRegistry, unmet_preconditions
from .skill import SkillManifest

ROUTER_PROMPT_VERSION = "router@1"
NONE = "none"
_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "for",
        "to",
        "in",
        "on",
        "with",
        "is",
        "are",
        "be",
        "this",
        "that",
        "these",
        "those",
        "we",
        "i",
        "you",
        "it",
        "our",
        "my",
        "me",
        "please",
        "can",
        "could",
        "would",
        "should",
        "do",
        "does",
        "how",
        "what",
        "which",
        "who",
        "need",
        "want",
        "let",
        "us",
        "all",
        "any",
        "some",
    ]
)


class RoutingError(ValueError):
    pass


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str | None
    method: Literal["explicit", "no-candidates", "single-candidate", "model", "lexical"]
    candidates: list[str]
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str
    model: dict[str, Any] | None = None


def _stem(word: str) -> str:
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ions", "ion"), ("es", ""), ("ed", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)] + replacement
    return word


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP}


def lexical_choice(message: str, candidates: list[SkillManifest]) -> tuple[str | None, dict[str, float]]:
    """Keyword-overlap baseline: intents count double, name and description once."""
    words = _terms(message)
    scores: dict[str, float] = {}
    for m in candidates:
        intent_terms = set().union(*(_terms(i) for i in m.intents)) if m.intents else set()
        other_terms = _terms(f"{m.name} {m.description}")
        scores[m.id] = 2 * len(words & intent_terms) + len(words & (other_terms - intent_terms))
    if not scores:
        return None, scores
    best = max(scores, key=lambda k: (scores[k], k))
    ranked = sorted(scores.values(), reverse=True)
    if scores[best] == 0 or (len(ranked) > 1 and ranked[0] == ranked[1]):
        return None, scores
    return best, scores


RATIONALE_MAX = 400


def _shorten(cls: type[BaseModel], value: object) -> object:
    """The rationale is display-only: an over-long one is truncated rather than failing the route.

    Measured: qwen3:4b-instruct wrote >400-character rationales for 2 of 30 routing cases, every
    repeat, and again on the repair attempt (run 37254103610), so the whole decision was lost.
    """
    if isinstance(value, str) and len(value) > RATIONALE_MAX:
        return value[: RATIONALE_MAX - 1].rstrip() + "…"
    return value


def _answer_model(ids: list[str]) -> type[BaseModel]:
    choice = Literal[(*ids, NONE)]  # type: ignore[valid-type]
    return create_model(
        "RouteAnswer",
        __config__=ConfigDict(extra="ignore"),
        __validators__={"_shorten_rationale": field_validator("rationale", mode="before")(_shorten)},
        skill_id=(choice, ...),
        confidence=(float, Field(ge=0, le=1)),
        rationale=(str, Field(min_length=1, max_length=RATIONALE_MAX)),
    )


def _messages(message: str, candidates: list[SkillManifest]) -> list[Message]:
    system = resources.files(__package__).joinpath("prompts/router_v1.md").read_text(encoding="utf-8")
    listing = "\n".join(
        f"- id: {m.id} | name: {m.name} | does: {m.description} | example requests: {'; '.join(m.intents)}"
        for m in candidates
    )
    safe = message.replace("</user_message>", "</ user_message>")
    user = f"Available skills:\n{listing}\n\n<user_message>\n{safe}\n</user_message>"
    return [Message(role="system", content=system), Message(role="user", content=user)]


class SkillRouter:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def check_explicit(self, skill_id: str, spec: ApplicationSpec) -> SkillManifest:
        try:
            manifest = self.registry.get(skill_id).manifest
        except RegistryError as exc:
            raise RoutingError(str(exc)) from exc
        missing = unmet_preconditions(manifest, spec)
        if missing:
            raise RoutingError(f"skill '{skill_id}' needs {', '.join(missing)} in the specification first")
        return manifest

    def route(
        self,
        message: str,
        spec: ApplicationSpec,
        *,
        provider: ModelProvider | None,
        budget: Budget,
        explicit: str | None = None,
        call_timeout_s: float = 60.0,
        prices: Prices | None = None,
    ) -> RouteDecision:
        candidates = self.registry.applicable(spec)
        ids = [m.id for m in candidates]
        if explicit is not None:
            self.check_explicit(explicit, spec)
            return RouteDecision(skill_id=explicit, method="explicit", candidates=ids, rationale="Chosen by the user.")
        if not candidates:
            return RouteDecision(
                skill_id=None, method="no-candidates", candidates=[], rationale="No skill applies yet."
            )
        if len(candidates) == 1:
            return RouteDecision(
                skill_id=ids[0],
                method="single-candidate",
                candidates=ids,
                rationale="Only one skill applies to the specification in its current state.",
            )
        if provider is None:
            raise ModelError(ErrorKind.NOT_CONFIGURED)
        result = generate_structured(
            provider,
            _messages(message, candidates),
            _answer_model(ids),
            budget=budget,
            max_repairs=1,
            call_timeout_s=call_timeout_s,
            prices=prices,
        )
        answer = result.value
        chosen = str(answer.skill_id)  # type: ignore[attr-defined]
        return RouteDecision(
            skill_id=None if chosen == NONE else chosen,
            method="model",
            candidates=ids,
            confidence=float(answer.confidence),  # type: ignore[attr-defined]
            rationale=str(answer.rationale),  # type: ignore[attr-defined]
            model={
                "model_id": result.model_id,
                "profile": result.profile,
                "prompt_version": ROUTER_PROMPT_VERSION,
                "usage": result.usage.model_dump() | {"total_tokens": result.usage.total_tokens},
                "repaired": result.repaired,
                "calls": [c.model_dump() for c in result.calls],
            },
        )
