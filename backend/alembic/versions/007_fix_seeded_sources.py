"""Fix seeded source configuration found broken by live testing

- greenhouse_tech_boards: drop boards that left Greenhouse (404), add verified ones, and allow
  larger, slower responses (Cloudflare's board is ~8 MB with descriptions).
- zindi_africa_competitions: Zindi's API moved to api.zindi.world.
- mlh_events: MLH has no public events API; the adapter now reads www.mlh.com season pages.

Rows are only updated while they still hold the originally seeded values, so changes an
admin made through the API are never overwritten.

Revision ID: 007_fix_seeded_sources
Revises: 006_run_reliability
Create Date: 2026-11-12
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_fix_seeded_sources"
down_revision: Union[str, None] = "006_run_reliability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_BOARDS = ["paystack", "moniepoint", "andela", "wave", "gitlab", "cloudflare"]
NEW_GREENHOUSE_CONFIG = {
    "board_tokens": ["moniepoint", "turing", "gitlab", "cloudflare", "twilio", "mongodb", "figma", "vercel", "elastic"],
    "max_response_mb": 25,
    "request_timeout_seconds": 90,
}

URL_CHANGES = [
    # (slug, old base_url, new base_url)
    ("zindi_africa_competitions", "https://zindi.africa/api/v1/competitions", "https://api.zindi.world/v1/competitions"),
    ("mlh_events", "https://mlh.io/api/v2/events", "https://www.mlh.com/seasons"),
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE sources
            SET adapter_config = CAST(:new_config AS jsonb),
                name = 'Greenhouse Public Job Boards (Remote & Africa Tech)'
            WHERE slug = 'greenhouse_tech_boards'
              AND adapter_config -> 'board_tokens' = CAST(:old_boards AS jsonb)
        """),
        {"new_config": json.dumps(NEW_GREENHOUSE_CONFIG), "old_boards": json.dumps(OLD_BOARDS)},
    )
    for slug, old_url, new_url in URL_CHANGES:
        conn.execute(
            sa.text("UPDATE sources SET base_url = :new WHERE slug = :slug AND base_url = :old"),
            {"slug": slug, "old": old_url, "new": new_url},
        )
    conn.execute(sa.text("UPDATE sources SET collection_method = 'STRUCTURED_DATA' WHERE slug = 'mlh_events'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE sources SET adapter_config = jsonb_build_object('board_tokens', CAST(:old_boards AS jsonb))
            WHERE slug = 'greenhouse_tech_boards' AND adapter_config = CAST(:new_config AS jsonb)
        """),
        {"new_config": json.dumps(NEW_GREENHOUSE_CONFIG), "old_boards": json.dumps(OLD_BOARDS)},
    )
    for slug, old_url, new_url in URL_CHANGES:
        conn.execute(
            sa.text("UPDATE sources SET base_url = :old WHERE slug = :slug AND base_url = :new"),
            {"slug": slug, "old": old_url, "new": new_url},
        )
