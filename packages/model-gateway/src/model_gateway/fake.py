"""Deterministic provider for tests and offline development. Never used to report model quality."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import ModelError
from .provider import RawCompletion
from .schema import Capabilities, Message, Usage

Reply = str | dict[str, Any] | ModelError | Callable[[list[Message]], "str | dict[str, Any]"]


@dataclass
class FakeProvider:
    """Returns scripted replies in order; records every request it receives."""

    replies: list[Reply]
    model_id: str = "fake-model"
    profile: str = "fake"
    capabilities: Capabilities = field(default_factory=lambda: Capabilities(remote=False))
    usage_per_call: Usage = field(default_factory=lambda: Usage(prompt_tokens=100, completion_tokens=50))
    requests: list[list[Message]] = field(default_factory=list)
    schemas: list[dict[str, Any] | None] = field(default_factory=list)

    def complete(
        self,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout_s: float,
    ) -> RawCompletion:
        self.requests.append(list(messages))
        self.schemas.append(json_schema)
        if not self.replies:
            raise AssertionError("FakeProvider ran out of scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, ModelError):
            raise reply
        if callable(reply):
            reply = reply(messages)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return RawCompletion(text=text, usage=self.usage_per_call, transport_attempts=1, latency_ms=1.0)
