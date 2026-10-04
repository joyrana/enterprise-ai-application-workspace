"""Provider protocol and the provider-neutral structured-generation loop.

Providers implement one primitive, :meth:`ModelProvider.complete` (one logical
call, including transport-level retries). Everything that must behave the same
for every provider — prompt framing, JSON extraction, validation, the single
repair attempt, budgets and telemetry — lives in :func:`generate_structured`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .budget import Budget
from .errors import ErrorKind, ModelError
from .extract import ExtractionError, extract_json_object
from .schema import CallRecord, Capabilities, Message, StructuredMode, StructuredResult, Usage


@dataclass(frozen=True)
class RawCompletion:
    text: str
    usage: Usage
    transport_attempts: int
    latency_ms: float


@dataclass(frozen=True)
class Prices:
    """USD per million tokens. Configure only from the provider's published price list."""

    input_per_mtok: float
    output_per_mtok: float

    def cost(self, usage: Usage) -> float:
        return round(
            usage.prompt_tokens * self.input_per_mtok / 1e6 + usage.completion_tokens * self.output_per_mtok / 1e6, 6
        )


class ModelProvider(Protocol):
    @property
    def profile(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    def complete(
        self,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout_s: float,
    ) -> RawCompletion: ...


SCHEMA_INSTRUCTIONS = (
    "Respond with exactly one JSON object that validates against the JSON Schema below. "
    "Do not add explanations, Markdown or code fences before or after the JSON."
)
_MAX_ERROR_FEEDBACK = 20


def _with_schema(messages: list[Message], schema: dict[str, Any]) -> list[Message]:
    block = f"{SCHEMA_INSTRUCTIONS}\n<json_schema>\n{json.dumps(schema, separators=(',', ':'))}\n</json_schema>"
    if messages and messages[0].role == "system":
        first = Message(role="system", content=f"{messages[0].content}\n\n{block}")
        return [first, *messages[1:]]
    return [Message(role="system", content=block), *messages]


def _validation_feedback(error: Exception) -> str:
    if isinstance(error, ValidationError):
        lines = []
        for item in error.errors()[:_MAX_ERROR_FEEDBACK]:
            loc = "/" + "/".join(str(p) for p in item.get("loc", ()))
            lines.append(f"- {loc}: {item.get('msg')}")
        return "\n".join(lines)
    return f"- {error}"


def generate_structured[T: BaseModel](
    provider: ModelProvider,
    messages: list[Message],
    output_type: type[T],
    *,
    budget: Budget,
    max_repairs: int = 1,
    call_timeout_s: float = 60.0,
    prices: Prices | None = None,
) -> StructuredResult[T]:
    """Ask for JSON matching ``output_type``; validate; repair at most ``max_repairs`` times.

    Raises :class:`ModelError` on provider failures, budget exhaustion, or when
    the output still does not validate after the repair attempts.
    """
    schema = output_type.model_json_schema()
    native = provider.capabilities.structured_mode is StructuredMode.JSON_SCHEMA
    conversation = _with_schema(messages, schema)
    calls: list[CallRecord] = []
    usage = Usage()
    attempt = 0

    while True:
        purpose = "initial" if attempt == 0 else "repair"
        budget.check()
        timeout = max(1.0, min(call_timeout_s, budget.remaining_s))
        try:
            raw = provider.complete(
                conversation,
                json_schema=schema if native else None,
                schema_name=output_type.__name__,
                timeout_s=timeout,
            )
        except ModelError as exc:
            calls.append(
                CallRecord(
                    model_id=provider.model_id,
                    profile=provider.profile,
                    purpose=purpose,
                    transport_attempts=1,
                    latency_ms=0.0,
                    usage=Usage(),
                    outcome="error",
                    error_kind=exc.kind.value,
                )
            )
            exc.calls = calls
            raise
        budget.record(raw.usage)
        usage = usage + raw.usage

        try:
            value = output_type.model_validate(extract_json_object(raw.text))
        except (ExtractionError, ValidationError) as exc:
            calls.append(
                CallRecord(
                    model_id=provider.model_id,
                    profile=provider.profile,
                    purpose=purpose,
                    transport_attempts=raw.transport_attempts,
                    latency_ms=raw.latency_ms,
                    usage=raw.usage,
                    outcome="schema_failure",
                    error_kind=ErrorKind.SCHEMA_FAILURE.value,
                )
            )
            if attempt >= max_repairs:
                raise ModelError(
                    ErrorKind.SCHEMA_FAILURE,
                    f"output invalid after {attempt + 1} attempt(s): {str(exc)[:300]}",
                    calls=calls,
                ) from exc
            attempt += 1
            conversation = [
                *conversation,
                Message(role="assistant", content=raw.text[:20_000]),
                Message(
                    role="user",
                    content=(
                        "Your previous answer was not valid for the required JSON Schema:\n"
                        f"{_validation_feedback(exc)}\n"
                        "Return the corrected JSON object only."
                    ),
                ),
            ]
            continue

        calls.append(
            CallRecord(
                model_id=provider.model_id,
                profile=provider.profile,
                purpose=purpose,
                transport_attempts=raw.transport_attempts,
                latency_ms=raw.latency_ms,
                usage=raw.usage,
                outcome="ok",
            )
        )
        return StructuredResult[output_type](  # type: ignore[valid-type]
            value=value,
            model_id=provider.model_id,
            profile=provider.profile,
            usage=usage,
            calls=calls,
            repaired=attempt > 0,
            estimated_cost_usd=prices.cost(usage) if prices else None,
        )
