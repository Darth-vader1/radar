"""Saved records: per-user bookmarks of businesses, jobs and events with notes and tags

Revision ID: 009_saved_records
Revises: 008_api_sources_terms
Create Date: 2026-11-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_saved_records"
down_revision: Union[str, None] = "008_api_sources_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=32)), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_saved_records_user_entity"),
    )
    op.create_index("ix_saved_records_user_created", "saved_records", ["user_id", "created_at"])
    op.create_index("ix_saved_records_tags", "saved_records", ["tags"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_saved_records_tags", table_name="saved_records")
    op.drop_index("ix_saved_records_user_created", table_name="saved_records")
    op.drop_table("saved_records")
