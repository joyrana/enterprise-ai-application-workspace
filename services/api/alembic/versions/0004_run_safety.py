"""Prompt-injection screening: record the scan and flagged proposals per run.

Revision ID: 0004_run_safety
Revises: 0003_run_routing
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_run_safety"
down_revision = "0003_run_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("safety", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "safety")
