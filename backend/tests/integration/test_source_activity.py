"""Sources list shows live run activity, the last finished run and the next scheduled run."""
from datetime import UTC, datetime, timedelta

import pytest
from test_auth_api import CSRF, register_and_login
from test_run_lifecycle import as_admin, create_source

from app.core.config import settings
from app.models.source import SourceRun
from app.modules.scraping.schedules import DEFAULT_SCHEDULES, next_run_at
from app.seed import default_sources

pytestmark = pytest.mark.integration
API = f"{settings.API_V1_PREFIX}/sources"


def test_next_run_at():
    now = datetime(2026, 11, 14, 5, 30, tzinfo=UTC)
    assert next_run_at("0 */6 * * *", now) == datetime(2026, 11, 14, 6, 0, tzinfo=UTC)
    assert next_run_at("0 1 * * 0", now) == datetime(2026, 11, 15, 1, 0, tzinfo=UTC)  # next Sunday
    assert next_run_at(None, now) is None
    assert next_run_at("not a cron", now) is None


def test_every_seeded_source_has_a_default_schedule():
    for source in default_sources():
        assert source["schedule_cron"] == DEFAULT_SCHEDULES.get(source["slug"]), source["slug"]
    assert "google_places_api" not in DEFAULT_SCHEDULES  # Google's terms forbid bulk storage
    # Remotive's terms allow about four calls a day.
    assert DEFAULT_SCHEDULES["remotive_tech_jobs"] == "0 */6 * * *"


async def add_run(db, source_id, status, minutes_ago, **values):
    started = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    async with db() as s:
        run = SourceRun(source_id=source_id, trigger_type="MANUAL", status=status, search_params={},
                        started_at=started, **values)
        s.add(run)
        await s.commit()
        return run.id


async def test_sources_list_reports_activity_and_next_run(client, db):
    await register_and_login(client)
    busy = await create_source(db, schedule_cron="0 */6 * * *")
    idle = await create_source(db)  # no schedule
    off = await create_source(db, schedule_cron="0 5 * * *", is_enabled=False)

    await add_run(db, busy, "FAILED", 120, finished_at=datetime.now(UTC) - timedelta(minutes=118),
                  error_summary="boom")
    await add_run(db, busy, "COMPLETED", 60, finished_at=datetime.now(UTC) - timedelta(minutes=55), records_created=7)
    running = await add_run(db, busy, "RUNNING", 2, pages_fetched=3, records_created=40)

    r = await client.get(API)
    assert r.status_code == 200, r.text
    by_id = {s["id"]: s for s in r.json()}

    b = by_id[str(busy)]
    assert b["active_run"]["id"] == str(running)
    assert (b["active_run"]["status"], b["active_run"]["pages_fetched"], b["active_run"]["records_created"]) == ("RUNNING", 3, 40)
    assert b["last_run"]["status"] == "COMPLETED" and b["last_run"]["records_created"] == 7  # newest finished
    next_at = datetime.fromisoformat(b["next_run_at"])
    assert next_at > datetime.now(UTC) and next_at.minute == 0 and next_at.hour % 6 == 0

    assert by_id[str(idle)]["active_run"] is None and by_id[str(idle)]["last_run"] is None
    assert by_id[str(idle)]["next_run_at"] is None  # no schedule
    assert by_id[str(off)]["next_run_at"] is None  # disabled sources are never scheduled

    single = (await client.get(f"{API}/{busy}")).json()
    assert single["active_run"]["id"] == str(running)


async def test_admin_sets_and_clears_a_schedule(client, db):
    await as_admin(client, db)
    source_id = await create_source(db)

    r = await client.patch(f"{API}/{source_id}", json={"schedule_cron": "0 */12 * * *"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["schedule_cron"] == "0 */12 * * *"
    assert (await client.get(f"{API}/{source_id}")).json()["next_run_at"] is not None

    bad = await client.patch(f"{API}/{source_id}", json={"schedule_cron": "every tuesday"}, headers=CSRF)
    assert bad.status_code == 422

    r = await client.patch(f"{API}/{source_id}", json={"schedule_cron": ""}, headers=CSRF)
    assert r.json()["schedule_cron"] is None


async def test_standard_users_cannot_change_schedules(client, db):
    await register_and_login(client)
    source_id = await create_source(db)
    r = await client.patch(f"{API}/{source_id}", json={"schedule_cron": "0 5 * * *"}, headers=CSRF)
    assert r.status_code == 403
