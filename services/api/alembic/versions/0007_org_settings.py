"""Organization settings: versioned policy sets (ADR-0018).

Revision ID: 0007_org_settings
Revises: 0006_builds
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_org_settings"
down_revision = "0006_builds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "org_settings",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("policies", postgresql.JSONB(), nullable=False),
        sa.Column("policies_version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("org_settings")
