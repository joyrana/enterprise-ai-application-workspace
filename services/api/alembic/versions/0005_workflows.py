"""Checkpointed multi-step workflows (ADR-0012).

Revision ID: 0005_workflows
Revises: 0004_run_safety
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_workflows"
down_revision = "0004_run_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("definition_id", sa.String(64), nullable=False),
        sa.Column("definition_version", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("idempotency_fingerprint", sa.String(80), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'awaiting_review', 'completed', 'failed', 'cancelled')",
            name="ck_workflows_status",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflows_tenant_idempotency_key"),
    )
    op.create_index("ix_workflows_tenant_project_created", "workflows", ["tenant_id", "project_id", "created_at"])
    op.add_column(
        "workflow_runs",
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("workflow_runs", sa.Column("workflow_step", sa.Integer(), nullable=True))
    op.create_index("ix_workflow_runs_workflow", "workflow_runs", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow", table_name="workflow_runs")
    op.drop_column("workflow_runs", "workflow_step")
    op.drop_column("workflow_runs", "workflow_id")
    op.drop_index("ix_workflows_tenant_project_created", table_name="workflows")
    op.drop_table("workflows")
