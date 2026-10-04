"""Runtime configuration, read once from environment variables.

Secrets (the database password) arrive only through ``DATABASE_URL`` and are
never logged: ``Settings.__repr__`` redacts them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    #: Trusts X-Dev-Tenant / X-Dev-User headers. Local development and tests only.
    DEV = "dev"


class ConfigError(RuntimeError):
    pass


def _redact_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    environment: Environment = Environment.DEVELOPMENT
    auth_mode: AuthMode = AuthMode.DEV
    cors_origins: tuple[str, ...] = ()
    max_body_bytes: int = 1_048_576
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not self.database_url.startswith("postgresql"):
            raise ConfigError("DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg://...)")
        if self.auth_mode is AuthMode.DEV and self.environment is Environment.PRODUCTION:
            raise ConfigError(
                "AUTH_MODE=dev trusts client-supplied identity headers and is refused when APP_ENV=production. "
                "Configure a real identity provider before deploying."
            )
        if self.max_body_bytes < 1024:
            raise ConfigError("MAX_BODY_BYTES must be at least 1024")
        if "*" in self.cors_origins:
            raise ConfigError("CORS_ORIGINS must list explicit origins; '*' is not allowed")

    def __repr__(self) -> str:
        return (
            f"Settings(database_url={_redact_url(self.database_url)!r}, environment={self.environment.value!r}, "
            f"auth_mode={self.auth_mode.value!r}, cors_origins={self.cors_origins!r}, "
            f"max_body_bytes={self.max_body_bytes})"
        )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = dict(os.environ if env is None else env)
        url = source.get("DATABASE_URL")
        if not url:
            raise ConfigError("DATABASE_URL is required (see .env.example)")
        try:
            environment = Environment(source.get("APP_ENV", "development"))
            auth_mode = AuthMode(source.get("AUTH_MODE", "dev"))
            max_body = int(source.get("MAX_BODY_BYTES", "1048576"))
        except ValueError as exc:
            raise ConfigError(f"invalid configuration: {exc}") from exc
        origins = tuple(o.strip() for o in source.get("CORS_ORIGINS", "").split(",") if o.strip())
        return cls(
            database_url=url,
            environment=environment,
            auth_mode=auth_mode,
            cors_origins=origins,
            max_body_bytes=max_body,
            log_level=source.get("LOG_LEVEL", "INFO").upper(),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
