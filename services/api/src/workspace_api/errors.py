"""Consistent RFC 9457 ``application/problem+json`` error responses.

Internal details (stack traces, SQL, configuration) are never returned to the
client; unexpected errors are logged server-side with the request id.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("workspace_api.errors")

PROBLEM_JSON = "application/problem+json"


class FieldError(BaseModel):
    path: str
    message: str
    code: str | None = None


class Problem(BaseModel):
    type: str = Field(description="Stable error code URI, e.g. 'urn:workspace:error:revision-conflict'.")
    title: str
    status: int
    detail: str | None = None
    request_id: str | None = None
    errors: list[FieldError] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class AppError(Exception):
    status = 400
    code = "bad-request"
    title = "Bad request"

    def __init__(self, detail: str | None = None, *, errors: list[FieldError] | None = None, **extensions: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors or []
        self.extensions = extensions


class Unauthenticated(AppError):
    status, code, title = 401, "unauthenticated", "Authentication required"


class NotFound(AppError):
    status, code, title = 404, "not-found", "Resource not found"


class IdempotencyConflict(AppError):
    status, code, title = 409, "idempotency-key-reused", "Idempotency key reused with a different request"


class RevisionConflict(AppError):
    status, code, title = 412, "revision-conflict", "The specification changed since you loaded it"


class PreconditionRequired(AppError):
    status, code, title = 428, "precondition-required", "If-Match header is required"


class SpecInvalid(AppError):
    status, code, title = 422, "spec-invalid", "The specification is not valid"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Not allowed"


class ModelPolicyDenied(AppError):
    status, code, title = 403, "model-policy-denied", "This project's data may not be sent to the configured model"


class ModelNotConfigured(AppError):
    status, code, title = 503, "model-not-configured", "No AI model is configured"


class TooManyRuns(AppError):
    status, code, title = 429, "too-many-active-runs", "Too many AI runs are already in progress"


class SkillNotApplicable(AppError):
    status, code, title = 422, "skill-not-applicable", "That skill cannot run on this project yet"


class RunNotApplicable(AppError):
    status, code, title = 409, "run-not-applicable", "This run has no proposals to apply"


class RunAlreadyApplied(AppError):
    status, code, title = 409, "run-already-applied", "Decisions for this run were already applied"


class WorkflowStateConflict(AppError):
    status, code, title = 409, "workflow-state-conflict", "The workflow cannot do that in its current state"


class BuildAlreadyActive(AppError):
    status, code, title = 409, "build-already-active", "A build of this project is already queued or running"


class PayloadTooLarge(AppError):
    status, code, title = 413, "payload-too-large", "Request body is too large"


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def problem_response(request: Request, problem: Problem, headers: dict[str, str] | None = None) -> JSONResponse:
    problem.request_id = _request_id(request)
    return JSONResponse(
        problem.model_dump(mode="json", exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_JSON,
        headers=headers,
    )


def _loc_to_path(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = [str(p) for p in loc if p not in ("body",)]
    return "/" + "/".join(parts) if parts else "/"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem_response(
            request,
            Problem(
                type=f"urn:workspace:error:{exc.code}",
                title=exc.title,
                status=exc.status,
                detail=exc.detail,
                errors=exc.errors,
                extensions=exc.extensions,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(path=_loc_to_path(e.get("loc", ())), message=str(e.get("msg", "invalid")), code=e.get("type"))
            for e in exc.errors()
        ]
        return problem_response(
            request,
            Problem(
                type="urn:workspace:error:validation-failed",
                title="Request validation failed",
                status=422,
                errors=errors,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return problem_response(
            request,
            Problem(type=f"urn:workspace:error:http-{exc.status_code}", title=str(exc.detail), status=exc.status_code),
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"request_id": _request_id(request)})
        return problem_response(
            request,
            Problem(
                type="urn:workspace:error:internal",
                title="Internal server error",
                status=500,
                detail="An unexpected error occurred. Quote the request id when reporting it.",
            ),
        )
