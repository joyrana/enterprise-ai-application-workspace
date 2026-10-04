"""OpenAI-compatible chat-completions provider.

One implementation serves every ADR-0007 profile because all of them expose
``POST {base_url}/chat/completions``:

* ``hf-router``   — Hugging Face Inference Providers (``https://router.huggingface.co/v1``), e.g. Qwen.
* ``self-hosted`` — vLLM / TGI serving open weights inside the organization.
* ``ollama``      — Ollama's OpenAI-compatible endpoint (``http://localhost:11434/v1``), e.g. gpt-oss.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .errors import ErrorKind, ModelError
from .provider import RawCompletion
from .schema import Capabilities, Message, StructuredMode, Usage

_MAX_RETRY_AFTER_S = 30.0


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, min(float(value), _MAX_RETRY_AFTER_S))
    except ValueError:
        return None


def _classify(status: int) -> ErrorKind:
    if status in (401, 403):
        return ErrorKind.AUTH
    if status == 404:
        return ErrorKind.NOT_FOUND
    if status == 408:
        return ErrorKind.TIMEOUT
    if status == 429:
        return ErrorKind.RATE_LIMITED
    if status >= 500:
        return ErrorKind.UNAVAILABLE
    return ErrorKind.BAD_REQUEST


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        profile: str,
        base_url: str,
        model_id: str,
        capabilities: Capabilities,
        api_key: str | None = None,
        max_retries: int = 2,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
        seed: int | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self._profile = profile
        self._model_id = model_id
        self._capabilities = capabilities
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._max_retries = max_retries
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._seed = seed
        self._client = httpx.Client(transport=transport, follow_redirects=False)
        self._sleep = sleep
        self._rng = rng
        self._clock = clock

    def __repr__(self) -> str:  # never include the API key
        return f"OpenAICompatibleProvider(profile={self._profile!r}, model_id={self._model_id!r}, url={self._url!r})"

    @property
    def profile(self) -> str:
        return self._profile

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def close(self) -> None:
        self._client.close()

    def _body(self, messages: list[Message], json_schema: dict[str, Any] | None, schema_name: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model_id,
            "messages": [m.model_dump() for m in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        if self._seed is not None:
            body["seed"] = self._seed
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": json_schema, "strict": False},
            }
        elif self._capabilities.structured_mode is StructuredMode.JSON_OBJECT:
            body["response_format"] = {"type": "json_object"}
        return body

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        return min(8.0, 0.5 * (2**attempt)) * (0.5 + self._rng() / 2)

    def complete(
        self,
        messages: list[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        timeout_s: float,
    ) -> RawCompletion:
        body = self._body(messages, json_schema, schema_name)
        started = self._clock()
        deadline = started + timeout_s
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ModelError(ErrorKind.TIMEOUT, f"no response within {timeout_s:.0f}s")
            error: ModelError
            try:
                response = self._client.post(self._url, json=body, headers=self._headers, timeout=remaining)
            except httpx.TimeoutException:
                error = ModelError(ErrorKind.TIMEOUT, "request timed out")
            except httpx.TransportError as exc:
                error = ModelError(ErrorKind.UNAVAILABLE, f"connection failed: {type(exc).__name__}")
            else:
                if response.status_code == 200:
                    return self._parse(response, attempt, started)
                kind = _classify(response.status_code)
                error = ModelError(
                    kind, f"HTTP {response.status_code} from provider", retry_after_s=_retry_after(response)
                )
            if not error.kind.transient or attempt > self._max_retries:
                raise error
            pause = self._backoff(attempt - 1, error.retry_after_s)
            if self._clock() + pause >= deadline:
                raise error
            self._sleep(pause)

    def _parse(self, response: httpx.Response, attempts: int, started: float) -> RawCompletion:
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            text = message.get("content") or ""
            usage_raw = payload.get("usage") or {}
            usage = Usage(
                prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
                completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            )
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError(ErrorKind.PROTOCOL, f"unexpected response shape: {type(exc).__name__}") from exc
        if not isinstance(text, str):
            raise ModelError(ErrorKind.PROTOCOL, "message content is not text")
        return RawCompletion(
            text=text,
            usage=usage,
            transport_attempts=attempts,
            latency_ms=round((self._clock() - started) * 1000, 1),
        )
