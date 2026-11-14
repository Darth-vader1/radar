"""Give the seeded sources default crawl schedules (only where none is set).

Revision ID: 010_default_schedules
Revises: 009_saved_records
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "010_default_schedules"
down_revision: Union[str, None] = "009_saved_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of app.modules.scraping.schedules.DEFAULT_SCHEDULES at the time of this migration.
SCHEDULES = {
    "remotive_tech_jobs": "0 */6 * * *",
    "greenhouse_tech_boards": "0 5 * * *",
    "devpost_hackathons": "10 4 * * *",
    "mlh_events": "20 4 * * *",
    "zindi_africa_competitions": "30 4 * * *",
    "kaggle_competitions": "40 4 * * *",
    "osm_overpass_businesses": "0 1 * * 0",
}


def upgrade() -> None:
    stmt = sa.text("UPDATE sources SET schedule_cron = :cron WHERE slug = :slug AND schedule_cron IS NULL")
    for slug, cron in SCHEDULES.items():
        op.execute(stmt.bindparams(cron=cron, slug=slug))


def downgrade() -> None:
    stmt = sa.text("UPDATE sources SET schedule_cron = NULL WHERE slug = :slug AND schedule_cron = :cron")
    for slug, cron in SCHEDULES.items():
        op.execute(stmt.bindparams(cron=cron, slug=slug))
