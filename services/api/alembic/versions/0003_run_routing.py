"""Routing: a run may start before its skill is known; record the routing decision.

Revision ID: 0003_run_routing
Revises: 0002_workflow_runs
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_run_routing"
down_revision = "0002_workflow_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("workflow_runs", "skill_id", existing_type=sa.String(64), nullable=True)
    op.alter_column("workflow_runs", "skill_version", existing_type=sa.String(32), nullable=True)
    op.add_column("workflow_runs", sa.Column("routing", postgresql.JSONB(), nullable=True))
    # Pre-2b runs stored the request text under "description"; normalise to "message".
    op.execute(
        "UPDATE workflow_runs SET input = jsonb_build_object('message', input->>'description') "
        "WHERE input ? 'description' AND NOT input ? 'message'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE workflow_runs SET input = jsonb_build_object('description', input->>'message') "
        "WHERE input ? 'message'"
    )
    op.execute("DELETE FROM workflow_runs WHERE skill_id IS NULL OR skill_version IS NULL")
    op.drop_column("workflow_runs", "routing")
    op.alter_column("workflow_runs", "skill_version", existing_type=sa.String(32), nullable=False)
    op.alter_column("workflow_runs", "skill_id", existing_type=sa.String(64), nullable=False)
