"""
Default crawl schedules (5-field cron, evaluated in UTC; Lagos is UTC+1).

Chosen per source: Remotive's terms allow ~4 calls a day; jobs change daily; events change
slowly, so the event sources are staggered through the early morning; businesses rarely change
and the Overpass crawl is long, so it runs weekly. Google Places has no default schedule:
Google's terms only allow storing place IDs (and coordinates for 30 days), so it must not be
bulk-crawled into the database.
"""
from datetime import datetime
from typing import Optional

from croniter import croniter

DEFAULT_SCHEDULES: dict[str, str] = {
    "remotive_tech_jobs": "0 */6 * * *",
    "greenhouse_tech_boards": "0 5 * * *",
    "devpost_hackathons": "10 4 * * *",
    "mlh_events": "20 4 * * *",
    "zindi_africa_competitions": "30 4 * * *",
    "kaggle_competitions": "40 4 * * *",
    "osm_overpass_businesses": "0 1 * * 0",
}


def next_run_at(cron_expr: Optional[str], now: datetime) -> Optional[datetime]:
    """The next time the scheduler will start this source (to within its one-minute tick)."""
    if not cron_expr or not croniter.is_valid(cron_expr):
        return None
    return croniter(cron_expr, now).get_next(datetime)
