"""Google place IDs on businesses, and manual-only, small-run guardrails for Google Places.

Revision ID: 011_google_places_guardrails
Revises: 010_default_schedules
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "011_google_places_guardrails"
down_revision: Union[str, None] = "010_default_schedules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("google_place_id", sa.String(length=255), nullable=True))
    op.create_index("ix_businesses_google_place_id", "businesses", ["google_place_id"])
    op.execute(sa.text(
        """
        UPDATE sources
        SET schedule_cron = NULL,
            crawl_budget_pages = LEAST(crawl_budget_pages, 3),
            adapter_config = COALESCE(adapter_config, '{}'::jsonb)
                || '{"manual_only": true, "default_query": "restaurants in Ikeja, Lagos"}'::jsonb
        WHERE slug = 'google_places_api'
        """
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE sources SET adapter_config = adapter_config - 'manual_only' - 'default_query' "
        "WHERE slug = 'google_places_api'"
    ))
    op.drop_index("ix_businesses_google_place_id", table_name="businesses")
    op.drop_column("businesses", "google_place_id")
