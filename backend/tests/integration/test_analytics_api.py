"""Analytics API: discoveries and runs over time, per-source health, geography and prize weeks."""
from datetime import datetime, timedelta, timezone

import pytest
from test_auth_api import register_and_login

from app.core.config import settings
from app.models.business import Business
from app.models.event import Event
from app.models.job import Job
from app.models.source import DeadLetterTask, ScrapingTask, Source, SourceRun

pytestmark = pytest.mark.integration
API = f"{settings.API_V1_PREFIX}/analytics"


def source(slug, name, module):
    return Source(slug=slug, name=name, module_type=module, source_category="test", base_url="https://x.example",
                  collection_method="API", adapter_key=slug)


def run(src, status, started, minutes=2, created=10, error=None):
    return SourceRun(source_id=src.id, status=status, started_at=started, error_summary=error,
                     finished_at=started + timedelta(minutes=minutes), records_created=created)


def job(i, src, country, days_ago=0, remote="ONSITE"):
    return Job(title=f"Job {i}", normalized_title=f"job {i}", company_name="Acme", normalized_company="acme",
               description="d", application_url=f"https://j.example/{i}", source_platform="greenhouse",
               original_source_url=f"https://j.example/{i}", country=country, remote_status=remote,
               primary_source_id=src.id, discovered_at=datetime.now(timezone.utc) - timedelta(days=days_ago))


async def seed(db):
    now = datetime.now(timezone.utc)
    async with db() as s:
        gh = source("gh", "Greenhouse", "JOB")
        dev = source("dev", "Devpost", "EVENT")
        idle = source("idle", "Idle Source", "EVENT")
        s.add_all([gh, dev, idle])
        await s.flush()
        s.add_all([
            job(1, gh, "Nigeria"), job(2, gh, "Worldwide", remote="REMOTE"), job(3, gh, " "),
            job(4, gh, "Remote", days_ago=3), job(5, gh, "Nigeria", days_ago=60),  # outside the window
        ])
        s.add_all([
            Event(name="Hack A", normalized_name="hack a", description="d", registration_url="https://e/1",
                  source_url="https://e/1", status="OPEN_REGISTRATION", delivery_mode="VIRTUAL",
                  primary_source_id=dev.id, registration_deadline=now + timedelta(days=2), prize_amount_usd_est=1000),
            Event(name="Hack B", normalized_name="hack b", description="d", registration_url="https://e/2",
                  source_url="https://e/2", status="OPEN_REGISTRATION", delivery_mode="PHYSICAL",
                  primary_source_id=dev.id, registration_deadline=now + timedelta(days=30), prize_amount_usd_est=500),
            Event(name="Too far", normalized_name="too far", description="d", registration_url="https://e/3",
                  source_url="https://e/3", status="OPEN_REGISTRATION",
                  registration_deadline=now + timedelta(weeks=20), prize_amount_usd_est=9999),
        ])
        s.add(Business(name="Shop", normalized_name="shop", country="Nigeria", city="Ikeja",
                       original_source_url="https://osm/1"))
        s.add_all([
            run(gh, "COMPLETED", now - timedelta(hours=1), minutes=4, created=20),
            run(gh, "PARTIAL_FAILURE", now - timedelta(days=1), minutes=2, created=10),
            run(gh, "FAILED", now - timedelta(days=1), minutes=0, created=0, error="Board fetch timed out"),
            run(gh, "RUNNING", now - timedelta(minutes=5)),  # unfinished: counted as a run, not in rates
            run(dev, "COMPLETED", now - timedelta(days=90)),  # outside the window, but still the last run
        ])
        task = ScrapingTask(source_id=gh.id, stage="FETCH", status="FAILED")
        s.add(task)
        await s.flush()
        s.add_all([
            DeadLetterTask(scraping_task_id=task.id, source_id=gh.id, stage="FETCH", input_snapshot={},
                           error_type="Timeout", error_message="x"),
            DeadLetterTask(scraping_task_id=task.id, source_id=gh.id, stage="FETCH", input_snapshot={},
                           error_type="Timeout", error_message="x", resolved_at=now),
        ])
        await s.commit()


async def test_analytics_trends_health_geography(client, db):
    await register_and_login(client)
    await seed(db)
    r = await client.get(API, params={"days": 7})
    assert r.status_code == 200, r.text
    data = r.json()

    assert len(data["discoveries"]) == 7  # one row per day, gaps filled with zeros
    assert sum(d["jobs"] for d in data["discoveries"]) == 4
    assert data["discoveries"][-1]["jobs"] == 3 and data["discoveries"][-1]["businesses"] == 1
    assert {"source": "Greenhouse", "entity_type": "JOB", "count": 4} in data["discoveries_by_source"]
    assert {"source": "Unknown source", "entity_type": "EVENT", "count": 1} in data["discoveries_by_source"]

    assert sum(d["completed"] for d in data["runs"]) == 1
    assert sum(d["partial"] + d["failed"] for d in data["runs"]) == 2

    health = {h["name"]: h for h in data["source_health"]}
    gh = health["Greenhouse"]
    assert (gh["runs"], gh["completed"], gh["partial"], gh["failed"]) == (4, 1, 1, 1)
    assert gh["success_rate_pct"] == 50.0  # (1 + 0.5) / 3 finished runs
    assert gh["avg_duration_seconds"] == 120.0 and gh["avg_records_created"] == 10.0
    assert gh["last_run_status"] == "RUNNING" and gh["open_failed_tasks"] == 1
    assert gh["last_error_message"] == "Board fetch timed out"  # taken from the run when the source has none
    dev = health["Devpost"]
    assert dev["runs"] == 0 and dev["success_rate_pct"] is None and dev["last_run_status"] == "COMPLETED"
    assert health["Idle Source"]["last_run_at"] is None

    geo = data["geography"]
    assert geo["jobs_total"] == 5 and geo["jobs_remote"] == 1 and geo["nigeria_jobs"] == 2
    assert geo["jobs_by_country"] == [
        {"name": "Anywhere", "count": 2}, {"name": "Nigeria", "count": 2}, {"name": "Not stated", "count": 1},
    ]
    assert geo["businesses_by_city"] == [{"name": "Ikeja", "count": 1}]

    prizes = data["prizes_by_deadline_week"]
    assert len(prizes) == 12
    assert sum(p["prize_usd"] for p in prizes) == 1500  # the event 20 weeks out is excluded
    assert sum(p["events"] for p in prizes) == 2


async def test_analytics_empty_and_validation(client, db):
    await register_and_login(client)
    data = (await client.get(API)).json()
    assert data["days"] == 30 and len(data["discoveries"]) == 30
    assert data["source_health"] == [] and data["geography"]["jobs_by_country"] == []
    assert (await client.get(API, params={"days": 3})).status_code == 422
    assert (await client.get(API, params={"days": 365})).status_code == 422


async def test_analytics_requires_auth(client, db):
    assert (await client.get(API)).status_code == 401
