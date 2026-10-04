"""Tests for the OpenAI-compatible provider over a real httpx transport (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from model_gateway import (
    Capabilities,
    ErrorKind,
    Message,
    ModelConfigError,
    ModelError,
    ModelSettings,
    OpenAICompatibleProvider,
    Profile,
    StructuredMode,
)

MSGS = [Message(role="user", content="hi")]


def ok(content: str = '{"a": 1}', usage: dict[str, int] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage or {"prompt_tokens": 12, "completion_tokens": 3},
        },
    )


class Recorder:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def body(self, index: int = 0) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.requests[index].content)
        return data


def provider(recorder: Recorder, **kwargs: Any) -> tuple[OpenAICompatibleProvider, list[float]]:
    sleeps: list[float] = []
    defaults: dict[str, Any] = {
        "profile": "ollama",
        "base_url": "http://localhost:11434/v1/",
        "model_id": "gpt-oss:20b",
        "capabilities": Capabilities(remote=False),
        "transport": httpx.MockTransport(recorder),
        "sleep": sleeps.append,
        "rng": lambda: 1.0,
    }
    defaults.update(kwargs)
    return OpenAICompatibleProvider(**defaults), sleeps


def test_request_shape_and_usage() -> None:
    rec = Recorder([ok()])
    p, _ = provider(rec, seed=7)
    raw = p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=30)
    assert raw.text == '{"a": 1}'
    assert raw.usage.prompt_tokens == 12
    assert raw.transport_attempts == 1
    req = rec.requests[0]
    assert str(req.url) == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in req.headers
    body = rec.body()
    assert body["model"] == "gpt-oss:20b"
    assert body["temperature"] == 0.0
    assert body["seed"] == 7
    assert body["stream"] is False
    assert "response_format" not in body


def test_bearer_token_sent_but_never_in_repr() -> None:
    rec = Recorder([ok()])
    p, _ = provider(rec, api_key="hf_secret_value", base_url="https://router.huggingface.co/v1", profile="hf-router")
    p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=30)
    assert rec.requests[0].headers["authorization"] == "Bearer hf_secret_value"
    assert "hf_secret_value" not in repr(p)


def test_json_schema_mode_sends_response_format() -> None:
    rec = Recorder([ok()])
    p, _ = provider(rec, capabilities=Capabilities(structured_mode=StructuredMode.JSON_SCHEMA, remote=False))
    p.complete(MSGS, json_schema={"type": "object"}, schema_name="Answer", timeout_s=30)
    fmt = rec.body()["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "Answer"


def test_json_object_mode() -> None:
    rec = Recorder([ok()])
    p, _ = provider(rec, capabilities=Capabilities(structured_mode=StructuredMode.JSON_OBJECT, remote=False))
    p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=30)
    assert rec.body()["response_format"] == {"type": "json_object"}


def test_retries_transient_errors_with_retry_after() -> None:
    rec = Recorder([httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(503), ok()])
    p, sleeps = provider(rec, max_retries=2)
    raw = p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60)
    assert raw.transport_attempts == 3
    assert sleeps == [2.0, 1.0]  # Retry-After honoured; then exponential backoff (rng=1.0)


def test_retries_are_bounded() -> None:
    rec = Recorder([httpx.Response(503), httpx.Response(503)])
    p, _ = provider(rec, max_retries=1)
    with pytest.raises(ModelError) as info:
        p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60)
    assert info.value.kind is ErrorKind.UNAVAILABLE
    assert len(rec.requests) == 2


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, ErrorKind.AUTH), (403, ErrorKind.AUTH), (404, ErrorKind.NOT_FOUND), (400, ErrorKind.BAD_REQUEST)],
)
def test_non_transient_errors_are_not_retried(status: int, kind: ErrorKind) -> None:
    rec = Recorder([httpx.Response(status, text="provider says no; key=hf_secret")])
    p, sleeps = provider(rec)
    with pytest.raises(ModelError) as info:
        p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60)
    assert info.value.kind is kind
    assert "hf_secret" not in str(info.value)  # provider bodies are never echoed
    assert sleeps == []
    assert len(rec.requests) == 1


def test_connection_errors_are_classified_and_retried() -> None:
    rec = Recorder([httpx.ConnectError("refused"), ok()])
    p, _ = provider(rec)
    assert p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60).transport_attempts == 2


def test_timeout_is_classified() -> None:
    rec = Recorder([httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow")])
    p, _ = provider(rec)
    with pytest.raises(ModelError) as info:
        p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60)
    assert info.value.kind is ErrorKind.TIMEOUT


def test_backoff_that_would_pass_deadline_stops_retrying() -> None:
    rec = Recorder([httpx.Response(429, headers={"Retry-After": "30"}), ok()])
    p, sleeps = provider(rec)
    with pytest.raises(ModelError) as info:
        p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=5)
    assert info.value.kind is ErrorKind.RATE_LIMITED
    assert sleeps == []


@pytest.mark.parametrize("payload", [{"choices": []}, {"nope": 1}, {"choices": [{"message": {"content": 5}}]}])
def test_malformed_provider_response(payload: dict[str, Any]) -> None:
    rec = Recorder([httpx.Response(200, json=payload)])
    p, _ = provider(rec)
    with pytest.raises(ModelError) as info:
        p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60)
    assert info.value.kind is ErrorKind.PROTOCOL


def test_null_content_is_empty_text() -> None:
    rec = Recorder([httpx.Response(200, json={"choices": [{"message": {"content": None}}]})])
    p, _ = provider(rec)
    assert p.complete(MSGS, json_schema=None, schema_name="X", timeout_s=60).text == ""


# --------------------------------------------------------------------------- configuration


def test_unset_profile_means_not_configured() -> None:
    assert ModelSettings.from_env({}) is None


def test_hf_router_profile_defaults() -> None:
    s = ModelSettings.from_env({"MODEL_PROFILE": "hf-router", "MODEL_ID": "Qwen/Qwen3-8B", "HF_TOKEN": "hf_x"})
    assert s is not None
    assert s.profile is Profile.HF_ROUTER
    assert s.base_url == "https://router.huggingface.co/v1"
    assert s.remote is True
    assert s.structured_mode is StructuredMode.PROMPT_AND_VALIDATE
    assert "hf_x" not in repr(s)
    assert s.label == "hf-router:Qwen/Qwen3-8B"


def test_ollama_profile_is_local() -> None:
    s = ModelSettings.from_env({"MODEL_PROFILE": "ollama", "MODEL_ID": "gpt-oss:20b"})
    assert s is not None
    assert (s.base_url, s.remote, s.api_key) == ("http://localhost:11434/v1", False, None)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MODEL_PROFILE": "openai"}, "MODEL_PROFILE must be one of"),
        ({"MODEL_PROFILE": "hf-router", "MODEL_ID": "Qwen/x"}, "HF_TOKEN is required"),
        ({"MODEL_PROFILE": "ollama"}, "MODEL_ID is required"),
        ({"MODEL_PROFILE": "self-hosted", "MODEL_ID": "q"}, "MODEL_BASE_URL is required"),
        (
            {
                "MODEL_PROFILE": "self-hosted",
                "MODEL_ID": "q",
                "MODEL_BASE_URL": "http://gpu:8000/v1",
                "MODEL_REMOTE": "1",
            },
            "must use https",
        ),
        ({"MODEL_PROFILE": "ollama", "MODEL_ID": "q", "MODEL_TIMEOUT_SECONDS": "abc"}, "invalid model configuration"),
        ({"MODEL_PROFILE": "ollama", "MODEL_ID": "q", "MODEL_STRUCTURED_MODE": "magic"}, "invalid model configuration"),
    ],
)
def test_invalid_configuration(env: dict[str, str], message: str) -> None:
    with pytest.raises(ModelConfigError, match=message):
        ModelSettings.from_env(env)
