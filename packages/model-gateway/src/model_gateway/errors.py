"""Classified model errors. User-facing text never includes secrets or raw provider bodies."""

from __future__ import annotations

from enum import StrEnum

from .schema import CallRecord


class ErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    POLICY_DENIED = "policy_denied"
    AUTH = "auth"
    NOT_FOUND = "model_not_found"
    BAD_REQUEST = "bad_request"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    PROTOCOL = "protocol"
    SCHEMA_FAILURE = "schema_failure"
    BUDGET_EXCEEDED = "budget_exceeded"

    @property
    def transient(self) -> bool:
        return self in {ErrorKind.RATE_LIMITED, ErrorKind.UNAVAILABLE, ErrorKind.TIMEOUT}


_MESSAGES: dict[ErrorKind, str] = {
    ErrorKind.NOT_CONFIGURED: "No AI model is configured for this workspace.",
    ErrorKind.POLICY_DENIED: "Policy does not allow this project's data to be sent to the configured model.",
    ErrorKind.AUTH: "The model provider rejected the configured credentials.",
    ErrorKind.NOT_FOUND: "The configured model was not found at the provider.",
    ErrorKind.BAD_REQUEST: "The model provider rejected the request.",
    ErrorKind.RATE_LIMITED: "The model provider is rate limiting requests. Try again shortly.",
    ErrorKind.UNAVAILABLE: "The model provider is unavailable. Try again shortly.",
    ErrorKind.TIMEOUT: "The model did not respond in time.",
    ErrorKind.PROTOCOL: "The model provider returned a response the workspace could not read.",
    ErrorKind.SCHEMA_FAILURE: "The model's answer did not match the required structure, even after a repair attempt.",
    ErrorKind.BUDGET_EXCEEDED: "The workflow reached its model-call, token or time budget.",
}


class ModelError(Exception):
    def __init__(
        self,
        kind: ErrorKind,
        detail: str | None = None,
        *,
        calls: list[CallRecord] | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        self.kind = kind
        #: Safe, short technical detail for logs and operators (no secrets, no prompt text).
        self.detail = detail
        self.calls = calls or []
        self.retry_after_s = retry_after_s
        super().__init__(f"{kind.value}: {detail}" if detail else kind.value)

    @property
    def user_message(self) -> str:
        return _MESSAGES[self.kind]
