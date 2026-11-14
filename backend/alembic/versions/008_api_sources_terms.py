"""Remotive and OSM Overpass: follow their API terms instead of crawler robots.txt

Both are public APIs whose robots.txt disallows their API paths for crawlers. Their usage is
governed by their own API terms, which this applies:

- remotive_tech_jobs: robots check off; at most 1 request/minute and >= 6 hours between runs
  (terms: max ~4 calls per day); one request per run, so the old category list is dropped.
- osm_overpass_businesses: robots check off; >= 1 hour between runs (fair-use policy); 90 s timeout
  (Overpass queries routinely take longer than the 20 s default).

Rows are only changed while they still hold the originally seeded values.

Revision ID: 008_api_sources_terms
Revises: 007_fix_seeded_sources
Create Date: 2026-11-13
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_api_sources_terms"
down_revision: Union[str, None] = "007_fix_seeded_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_REMOTIVE_CONFIG = {"categories": ["software-dev", "data", "devops", "qa"]}
NEW_REMOTIVE_CONFIG = {"min_run_interval_minutes": 360}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE sources
            SET respect_robots_txt = false, rate_limit_rpm = 1, crawl_budget_pages = 1,
                adapter_config = CAST(:new AS jsonb)
            WHERE slug = 'remotive_tech_jobs' AND respect_robots_txt = true
              AND adapter_config = CAST(:old AS jsonb)
        """),
        {"new": json.dumps(NEW_REMOTIVE_CONFIG), "old": json.dumps(OLD_REMOTIVE_CONFIG)},
    )
    conn.execute(
        sa.text("""
            UPDATE sources
            SET respect_robots_txt = false,
                adapter_config = adapter_config || '{"min_run_interval_minutes": 60, "request_timeout_seconds": 90}'::jsonb
            WHERE slug = 'osm_overpass_businesses' AND respect_robots_txt = true
              AND NOT (adapter_config ? 'min_run_interval_minutes')
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE sources
            SET respect_robots_txt = true, rate_limit_rpm = 20, crawl_budget_pages = 50,
                adapter_config = CAST(:old AS jsonb)
            WHERE slug = 'remotive_tech_jobs' AND adapter_config = CAST(:new AS jsonb)
        """),
        {"new": json.dumps(NEW_REMOTIVE_CONFIG), "old": json.dumps(OLD_REMOTIVE_CONFIG)},
    )
    conn.execute(
        sa.text("""
            UPDATE sources
            SET respect_robots_txt = true,
                adapter_config = adapter_config - 'min_run_interval_minutes' - 'request_timeout_seconds'
            WHERE slug = 'osm_overpass_businesses'
        """)
    )
