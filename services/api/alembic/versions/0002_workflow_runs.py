"""Workflow runs: skill executions and proposals awaiting a decision.

Revision ID: 0002_workflow_runs
Revises: 0001_initial
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_workflow_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("skill_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("model", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("decisions", postgresql.JSONB(), nullable=True),
        sa.Column("applied_revision", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("idempotency_fingerprint", sa.String(80), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_workflow_runs_status"
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_workflow_runs_tenant_idempotency_key"),
    )
    op.create_index(
        "ix_workflow_runs_tenant_project_created", "workflow_runs", ["tenant_id", "project_id", "created_at"]
    )
    op.create_index("ix_workflow_runs_tenant_status", "workflow_runs", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_tenant_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_tenant_project_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")
