"""Initial schema: projects, immutable spec revisions, audit events.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("idempotency_fingerprint", sa.String(80), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_projects_tenant_idempotency_key"),
    )
    op.create_index("ix_projects_tenant_created", "projects", ["tenant_id", "created_at", "id"])

    op.create_table(
        "spec_revisions",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("semantic_hash", sa.String(80), nullable=False),
        sa.Column("change_summary", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Revisions are append-only: reject UPDATE at the database level as defence in depth.
    op.execute(
        """
        CREATE FUNCTION spec_revisions_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'spec_revisions rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER spec_revisions_no_update BEFORE UPDATE ON spec_revisions "
        "FOR EACH ROW EXECUTE FUNCTION spec_revisions_immutable();"
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_audit_tenant_project_id", "audit_events", ["tenant_id", "project_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_tenant_project_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.execute("DROP TRIGGER IF EXISTS spec_revisions_no_update ON spec_revisions;")
    op.execute("DROP FUNCTION IF EXISTS spec_revisions_immutable();")
    op.drop_table("spec_revisions")
    op.drop_index("ix_projects_tenant_created", table_name="projects")
    op.drop_table("projects")
