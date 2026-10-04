"""Application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Settings, get_settings
from .db import Database
from .errors import install_error_handlers
from .middleware import RequestContextMiddleware
from .routes import api, ops


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        db.dispose()

    app = FastAPI(
        title="Enterprise AI Application Workspace API",
        version=__version__,
        description=(
            "Projects, canonical application specifications and audit history. "
            "Development auth: send `X-Dev-Tenant` and `X-Dev-User` headers."
        ),
        lifespan=lifespan,
    )
    app.state.db = db
    app.state.settings = settings
    install_error_handlers(app)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Content-Type", "If-Match", "Idempotency-Key", "X-Dev-Tenant", "X-Dev-User", "X-Request-Id"],
            expose_headers=["ETag", "Location", "X-Request-Id", "X-Revision-Created"],
        )
    # Outermost: every response (including CORS preflight and errors) gets a request id and security headers.
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.max_body_bytes)
    app.include_router(ops)
    app.include_router(api)
    return app
