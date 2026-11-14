"""Provider usage terms: Remotive's ~4 calls/day cap and per-source minimum run intervals."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update
from test_auth_api import CSRF
from test_run_lifecycle import as_admin, create_run, create_source

from app.core.config import settings
from app.models.source import RunStatus, SourceRun
from app.modules.jobs.adapters.remotive import RemotiveJobsAdapter
from app.modules.scraping.adapter_base import RateLimitPolicy
from app.modules.scraping.runs import RunTooSoonError, check_run_interval
from app.modules.scraping.scheduling import dispatch_due_sources
from app.seed import default_sources

pytestmark = pytest.mark.integration
API = settings.API_V1_PREFIX
UTC = timezone.utc


@pytest.fixture
def queue(monkeypatch):
    from app.modules.scraping import runs as runs_module

    sent = []

    async def fake_enqueue(run_id):
        sent.append(run_id)
        return "task"

    monkeypatch.setattr(runs_module, "enqueue_run", fake_enqueue)
    return sent


async def test_remotive_makes_exactly_one_request_per_run():
    seeds = [s async for s in RemotiveJobsAdapter({}, RateLimitPolicy()).discover({})]
    assert [s.url for s in seeds] == ["https://remotive.com/api/remote-jobs"]


def test_seeded_terms_for_api_sources():
    by_slug = {s["slug"]: s for s in default_sources()}
    remotive, overpass = by_slug["remotive_tech_jobs"], by_slug["osm_overpass_businesses"]
    assert remotive["respect_robots_txt"] is False and overpass["respect_robots_txt"] is False
    assert remotive["adapter_config"]["min_run_interval_minutes"] >= 360  # <= 4 calls/day
    assert remotive["rate_limit_rpm"] <= 2  # provider blocks > 2/minute
    # Every other source keeps honouring robots.txt.
    assert all(s.get("respect_robots_txt", True) for slug, s in by_slug.items()
               if slug not in ("remotive_tech_jobs", "osm_overpass_businesses"))


async def _source_with_interval(db, minutes=360):
    return await create_source(db, adapter_config={"min_run_interval_minutes": minutes})


async def test_second_run_within_interval_is_refused(db):
    source_id = await _source_with_interval(db)
    run_id = await create_run(db, source_id, RunStatus.COMPLETED.value)
    async with db() as s:
        await s.execute(update(SourceRun).where(SourceRun.id == run_id)
                        .values(started_at=datetime.now(UTC) - timedelta(hours=2)))
        await s.commit()
        from sqlalchemy import select

        from app.models.source import Source
        source = await s.scalar(select(Source).where(Source.id == source_id))
        with pytest.raises(RunTooSoonError) as exc:
            await check_run_interval(s, source)
    assert 3.9 * 3600 < exc.value.retry_after_seconds <= 4 * 3600 + 1  # ~4 h left of 6 h


async def test_run_allowed_once_interval_has_passed(db):
    source_id = await _source_with_interval(db)
    run_id = await create_run(db, source_id, RunStatus.COMPLETED.value)
    async with db() as s:
        await s.execute(update(SourceRun).where(SourceRun.id == run_id)
                        .values(started_at=datetime.now(UTC) - timedelta(hours=7)))
        await s.commit()
        from sqlalchemy import select

        from app.models.source import Source
        await check_run_interval(s, await s.scalar(select(Source).where(Source.id == source_id)))


async def test_run_that_never_reached_the_provider_does_not_count(db):
    source_id = await _source_with_interval(db)
    await create_run(db, source_id, RunStatus.FAILED.value)  # e.g. queue down: never started
    async with db() as s:
        from sqlalchemy import select

        from app.models.source import Source
        await check_run_interval(s, await s.scalar(select(Source).where(Source.id == source_id)))


async def test_trigger_inside_interval_returns_429_with_retry_after(client, db, queue):
    await as_admin(client, db)
    source_id = await _source_with_interval(db)

    first = await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)
    assert first.status_code == 202
    async with db() as s:  # the worker picked it up and finished
        await s.execute(update(SourceRun).where(SourceRun.id == uuid.UUID(first.json()["id"]))
                        .values(status=RunStatus.COMPLETED.value, started_at=datetime.now(UTC)))
        await s.commit()

    second = await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 5 * 3600
    assert "usage terms" in second.json()["detail"]
    assert len(queue) == 1


async def test_scheduler_skips_source_inside_its_interval(db, queue):
    source_id = await create_source(db, schedule_cron="* * * * *", adapter_config={"min_run_interval_minutes": 360})
    run_id = await create_run(db, source_id, RunStatus.COMPLETED.value)
    async with db() as s:
        await s.execute(update(SourceRun).where(SourceRun.id == run_id)
                        .values(started_at=datetime.now(UTC) - timedelta(minutes=30), trigger_type="SCHEDULED"))
        await s.commit()

    assert await dispatch_due_sources(sessionmaker=db, now=datetime.now(UTC) + timedelta(minutes=5)) == []
    assert queue == []
