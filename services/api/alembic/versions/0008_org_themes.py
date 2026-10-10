"""Organization brand themes next to the policy set.

Revision ID: 0008_org_themes
Revises: 0007_org_settings
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_org_themes"
down_revision = "0007_org_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_settings",
        sa.Column("themes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "org_settings", sa.Column("themes_version", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )


def downgrade() -> None:
    op.drop_column("org_settings", "themes_version")
    op.drop_column("org_settings", "themes")
