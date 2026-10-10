"""Build requests for the isolated build runner (ADR-0015).

Revision ID: 0006_builds
Revises: 0005_workflows
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_builds"
down_revision = "0005_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "builds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("spec_revision", sa.Integer(), nullable=False),
        sa.Column("generator", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=True),
        sa.Column("requested_by", sa.String(128), nullable=False),
        sa.Column("worker", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out', 'output_too_large', "
            "'rejected', 'runner_error')",
            name="ck_builds_status",
        ),
    )
    op.create_index("ix_builds_tenant_project_created", "builds", ["tenant_id", "project_id", "created_at"])
    op.create_index("ix_builds_status_created", "builds", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_builds_status_created", table_name="builds")
    op.drop_index("ix_builds_tenant_project_created", table_name="builds")
    op.drop_table("builds")
