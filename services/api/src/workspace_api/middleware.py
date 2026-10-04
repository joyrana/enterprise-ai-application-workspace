"""ASGI middleware: request ids, body-size limit, security headers, access logs."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("workspace_api.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-resource-policy", b"same-site"),
    (b"cache-control", b"no-store"),
)


class RequestContextMiddleware:
    """Assigns a request id, enforces the body limit, adds security headers and logs one line per request.

    The request body is buffered up to ``max_body_bytes`` before the app runs,
    so chunked requests without a Content-Length cannot bypass the limit.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_body_bytes:
            await self._reject(send, request_id)
            self._log(scope, 413, start, request_id)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                self._log(scope, 499, start, request_id)
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_body_bytes:
                await self._reject(send, request_id)
                self._log(scope, 413, start, request_id)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        buffered: Message | None = {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        async def replay() -> Message:
            nonlocal buffered
            if buffered is not None:
                message, buffered = buffered, None
                return message
            return await receive()

        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode()),
                    *SECURITY_HEADERS,
                ]
            await send(message)

        try:
            await self.app(scope, replay, send_wrapper)
        finally:
            self._log(scope, status, start, request_id)

    async def _reject(self, send: Send, request_id: str) -> None:
        body = json.dumps(
            {
                "type": "urn:workspace:error:payload-too-large",
                "title": "Request body is too large",
                "status": 413,
                "detail": f"The limit is {self.max_body_bytes} bytes.",
                "request_id": request_id,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", request_id.encode()),
                    *SECURITY_HEADERS,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _log(scope: Scope, status: int, start: float, request_id: str) -> None:
        # Never log bodies, query strings or headers: they may contain spec content or identity data.
        fields: dict[str, Any] = {
            "event": "http.request",
            "request_id": request_id,
            "method": scope.get("method"),
            "path": scope.get("path"),
            "status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        }
        log.info(json.dumps(fields))
