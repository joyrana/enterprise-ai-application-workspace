"""Database models and session management (SQLAlchemy 2.0, PostgreSQL).

Tables:

* ``projects`` — one row per project, scoped by ``tenant_id``. Caches the
  project name from the latest spec and the current revision number.
* ``spec_revisions`` — immutable, append-only spec documents. A revision is
  never updated after insert; history is the audit trail of the spec.
* ``audit_events`` — append-only security- and change-relevant events.
* ``workflow_runs`` — skill executions and the proposals awaiting a decision.

Every query in the service layer filters on ``tenant_id``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_projects_tenant_idempotency_key"),
        Index("ix_projects_tenant_created", "tenant_id", "created_at", "id"),
    )


class SpecRevision(Base):
    __tablename__ = "spec_revisions"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    semantic_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    change_summary: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_audit_tenant_project_id", "tenant_id", "project_id", "id"),)


RUN_STATUSES = ("queued", "running", "succeeded", "failed")


class WorkflowRun(Base):
    """One execution of a skill against a project. Holds proposals until a person decides on them.

    The description a person typed is stored in ``input`` (tenant-scoped project
    data). Model telemetry in ``model`` never contains prompt or completion text.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: Null until routing has chosen a skill (or when no skill fits the request).
    skill_id: Mapped[str | None] = mapped_column(String(64))
    skill_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    routing: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: Deterministic injection scan of the message, plus proposals that echo flagged text.
    safety: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    base_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decisions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    applied_revision: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES!r}", name="ck_workflow_runs_status"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_runs_tenant_idempotency_key"),
        Index("ix_workflow_runs_tenant_project_created", "tenant_id", "project_id", "created_at"),
        Index("ix_workflow_runs_tenant_status", "tenant_id", "status"),
    )


class Database:
    """Owns the engine and session factory for one application instance."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            yield session

    def new_session(self) -> Session:
        """A session owned by the caller (background work outside a request). Close it when done."""
        return self._sessions()

    def dispose(self) -> None:
        self.engine.dispose()
