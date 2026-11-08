"""
Phase 3: reliable job execution. Exercises the run lifecycle against PostgreSQL with the
network faked and the Celery queue replaced by a recorder (or a failing publisher).
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.event import Event
from app.models.job import Job
from app.models.source import DeadLetterTask, ExtractedRecord, RunStatus, Source, SourceRun
from app.modules.adapters_loader import load_adapters
from app.modules.jobs.services.job_service import JobIngestionService
from app.modules.scraping import pipeline as pipeline_module
from app.modules.scraping import runs as runs_module
from app.modules.scraping.adapter_base import DiscoverySeed, RawFetchArtifact
from app.modules.scraping.pipeline import RETRY_SEEDS_KEY, PipelineOrchestrator, seed_to_snapshot
from app.modules.scraping.runs import QueueUnavailableError
from app.modules.scraping.scheduling import (
    dispatch_due_sources,
    is_due,
    reap_stale_runs,
    refresh_event_statuses,
)
from test_auth_api import CSRF, make_admin, register_and_login
from test_pipeline_e2e import SOURCES, _fixture_for

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
UTC = timezone.utc


# --- fixtures & helpers -------------------------------------------------------

@pytest.fixture
def db(db_sessionmaker, monkeypatch):
    load_adapters()
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", db_sessionmaker)
    return db_sessionmaker


@pytest.fixture
def queue(monkeypatch):
    """Records run ids instead of publishing to Celery."""
    sent: list[uuid.UUID] = []

    async def fake_enqueue(run_id):
        sent.append(run_id)
        return f"task-{len(sent)}"

    monkeypatch.setattr(runs_module, "enqueue_run", fake_enqueue)
    return sent


def make_gateway(on_fetch=None, fail_prefixes=()):
    async def fetch(seed, rate_policy=None):
        gw.calls.append(seed)
        if on_fetch:
            await on_fetch(seed, len(gw.calls))
        if any(seed.url.startswith(p) for p in fail_prefixes):
            raise RuntimeError("upstream returned 502")
        return RawFetchArtifact(
            seed=seed,
            final_url=seed.url,
            status_code=200,
            content_type="application/json",
            body_text=json.dumps(_fixture_for(seed.url)),
            fetched_at=datetime.now(UTC),
        )

    gw = SimpleNamespace(calls=[], close=AsyncMock())
    gw.fetch = AsyncMock(side_effect=fetch)
    return gw


async def create_source(db, adapter_key="remotive_jobs", slug=None, **overrides) -> uuid.UUID:
    async with db() as s:
        fields = dict(
            slug=slug or f"{adapter_key}-{uuid.uuid4().hex[:6]}",
            name=f"Test {adapter_key}",
            collection_method="OFFICIAL_API",
            adapter_key=adapter_key,
            adapter_config={},
            rate_limit_rpm=60,
            max_concurrency=1,
            crawl_budget_pages=10,
            is_enabled=True,
            respect_robots_txt=True,
            required_env_vars=[],
            **SOURCES[adapter_key],
        )
        source = Source(**{**fields, **overrides})
        s.add(source)
        await s.commit()
        return source.id


async def create_run(db, source_id, status=RunStatus.QUEUED.value, **values) -> uuid.UUID:
    async with db() as s:
        run = SourceRun(source_id=source_id, trigger_type="MANUAL", status=status, search_params={}, **values)
        s.add(run)
        await s.commit()
        return run.id


async def get_run(db, run_id) -> SourceRun:
    async with db() as s:
        return await s.scalar(select(SourceRun).where(SourceRun.id == run_id))


async def set_status(db, run_id, status):
    async with db() as s:
        await s.execute(
            update(SourceRun).where(SourceRun.id == run_id).values(status=status, finished_at=datetime.now(UTC))
        )
        await s.commit()


async def execute(db, run_id, gateway=None):
    gateway = gateway or make_gateway()
    await PipelineOrchestrator(gateway=gateway).execute_run(run_id)
    return await get_run(db, run_id), gateway


async def as_admin(client, db):
    email, _ = await register_and_login(client)
    await make_admin(db, email)


# --- dispatch ---------------------------------------------------------------

async def test_trigger_queues_run_and_rejects_a_second_active_run(client, db, queue):
    await as_admin(client, db)
    source_id = await create_source(db)

    r = await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "QUEUED"
    assert queue == [uuid.UUID(r.json()["id"])]

    again = await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)
    assert again.status_code == 409
    assert len(queue) == 1


async def test_trigger_fails_run_and_returns_503_when_queue_is_down(client, db, monkeypatch):
    await as_admin(client, db)
    source_id = await create_source(db)

    async def broken_enqueue(run_id):
        raise QueueUnavailableError("ConnectionError: redis down")

    monkeypatch.setattr(runs_module, "enqueue_run", broken_enqueue)

    r = await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)
    assert r.status_code == 503

    async with db() as s:
        run = await s.scalar(select(SourceRun).where(SourceRun.source_id == source_id))
    assert run.status == RunStatus.FAILED.value
    assert "queue unavailable" in run.error_summary.lower()

    # The failed run does not block the source: once the queue is back, triggering works.
    monkeypatch.setattr(runs_module, "enqueue_run", AsyncMock(return_value="task-1"))
    assert (await client.post(f"{API}/tasks/trigger", json={"source_id": str(source_id)}, headers=CSRF)).status_code == 202


async def test_database_enforces_one_active_run_per_source(db):
    source_id = await create_source(db)
    await create_run(db, source_id, RunStatus.QUEUED.value)

    with pytest.raises(IntegrityError, match="uq_source_runs_one_active_per_source"):
        await create_run(db, source_id, RunStatus.RUNNING.value)

    # Finished runs don't count.
    await create_run(db, source_id, RunStatus.COMPLETED.value)


async def test_trigger_rejects_reserved_retry_key(client, db, queue):
    await as_admin(client, db)
    source_id = await create_source(db)
    r = await client.post(
        f"{API}/tasks/trigger",
        json={"source_id": str(source_id), "search_params": {RETRY_SEEDS_KEY: [{"url": "https://example.com"}]}},
        headers=CSRF,
    )
    assert r.status_code == 400
    assert queue == []


# --- cancellation & redelivery ----------------------------------------------

async def test_cancel_mid_run_stops_before_the_next_page(db):
    source_id = await create_source(db, "devpost_hackathons")  # discovers 2 pages
    run_id = await create_run(db, source_id)

    async def cancel_during_first_fetch(seed, n):
        if n == 1:
            await set_status(db, run_id, RunStatus.CANCELLED.value)

    run, gw = await execute(db, run_id, make_gateway(on_fetch=cancel_during_first_fetch))

    assert len(gw.calls) == 1, "page 2 must not be fetched after cancel"
    assert run.status == RunStatus.CANCELLED.value  # not overwritten with COMPLETED
    assert run.pages_fetched == 1
    assert run.records_created == 1  # work done before the cancel is kept and counted


async def test_run_cancelled_while_queued_never_executes(db):
    run_id = await create_run(db, await create_source(db))
    await set_status(db, run_id, RunStatus.CANCELLED.value)

    run, gw = await execute(db, run_id)

    assert gw.calls == []
    assert run.status == RunStatus.CANCELLED.value


async def test_cancel_endpoint_does_not_overwrite_finished_run(client, db):
    await as_admin(client, db)
    run_id = await create_run(db, await create_source(db), RunStatus.COMPLETED.value)

    r = await client.post(f"{API}/tasks/runs/{run_id}/cancel", headers=CSRF)

    assert r.status_code == 400
    assert (await get_run(db, run_id)).status == RunStatus.COMPLETED.value


async def test_cancel_endpoint_cancels_running_run(client, db):
    await as_admin(client, db)
    run_id = await create_run(db, await create_source(db), RunStatus.RUNNING.value)

    r = await client.post(f"{API}/tasks/runs/{run_id}/cancel", headers=CSRF)

    assert r.status_code == 200
    assert r.json()["status"] == RunStatus.CANCELLED.value


async def test_run_left_running_by_crashed_worker_is_resumed_on_redelivery(db):
    run_id = await create_run(db, await create_source(db), RunStatus.RUNNING.value)

    run, _ = await execute(db, run_id)

    assert run.status == RunStatus.COMPLETED.value
    assert run.records_created == 2


async def test_finished_run_is_not_executed_again_on_duplicate_delivery(db):
    run_id = await create_run(db, await create_source(db))
    await execute(db, run_id)

    run, gw = await execute(db, run_id)

    assert gw.calls == []
    assert run.records_created == 2


# --- dead-letter retry --------------------------------------------------------

def test_dead_letter_snapshot_strips_credentials():
    seed = DiscoverySeed(
        url="https://places.googleapis.com/v1/places:searchText",
        method="POST",
        headers={"X-Goog-Api-Key": "secret-key", "Authorization": "Bearer t", "Content-Type": "application/json"},
        body={"textQuery": "restaurants in Ikeja"},
    )
    snap = seed_to_snapshot(seed)
    assert snap["headers"] == {"Content-Type": "application/json"}
    assert snap["headers_redacted"] is True
    assert "secret-key" not in json.dumps(snap)
    assert snap["method"] == "POST" and snap["body"] == {"textQuery": "restaurants in Ikeja"}


async def test_failed_fetch_is_dead_lettered_and_retry_recovers_it(client, db, queue):
    await as_admin(client, db)
    source_id = await create_source(db)
    first_run_id = await create_run(db, source_id)

    first, _ = await execute(db, first_run_id, make_gateway(fail_prefixes=("https://remotive.com",)))
    assert first.status == RunStatus.FAILED.value
    async with db() as s:
        dlq = await s.scalar(select(DeadLetterTask))
    assert dlq.stage == "FETCH"
    assert dlq.input_snapshot["seed"]["url"].startswith("https://remotive.com")

    r = await client.post(f"{API}/tasks/dead-letter/{dlq.id}/retry", headers=CSRF)
    assert r.status_code == 202, r.text
    retry_run_id = uuid.UUID(r.json()["source_run_id"])
    assert queue == [retry_run_id]

    retry_run = await get_run(db, retry_run_id)
    assert retry_run.trigger_type == "DLQ_RETRY"
    assert retry_run.search_params[RETRY_SEEDS_KEY][0]["url"] == dlq.input_snapshot["seed"]["url"]

    done, gw = await execute(db, retry_run_id)
    assert done.status == RunStatus.COMPLETED.value
    assert [s.url for s in gw.calls] == [dlq.input_snapshot["seed"]["url"]]  # only the failed page
    assert done.records_created == 2

    async with db() as s:
        resolved = await s.scalar(select(DeadLetterTask).where(DeadLetterTask.id == dlq.id))
    assert resolved.resolved_at is not None and str(retry_run_id) in resolved.resolution_note

    again = await client.post(f"{API}/tasks/dead-letter/{dlq.id}/retry", headers=CSRF)
    assert again.status_code == 409


async def test_retry_is_not_marked_resolved_when_queue_is_down(client, db, monkeypatch):
    await as_admin(client, db)
    source_id = await create_source(db)
    await execute(db, await create_run(db, source_id), make_gateway(fail_prefixes=("https://remotive.com",)))
    async with db() as s:
        dlq_id = (await s.scalar(select(DeadLetterTask))).id

    monkeypatch.setattr(runs_module, "enqueue_run", AsyncMock(side_effect=QueueUnavailableError("down")))
    r = await client.post(f"{API}/tasks/dead-letter/{dlq_id}/retry", headers=CSRF)

    assert r.status_code == 503
    async with db() as s:
        assert (await s.scalar(select(DeadLetterTask).where(DeadLetterTask.id == dlq_id))).resolved_at is None


async def test_item_that_failed_to_store_is_ingested_by_the_next_run(db, monkeypatch):
    source_id = await create_source(db)
    monkeypatch.setattr(JobIngestionService, "ingest_job", AsyncMock(side_effect=RuntimeError("db hiccup")))
    first, _ = await execute(db, await create_run(db, source_id))
    assert first.records_created == 0 and first.errors_count == 2
    monkeypatch.undo()
    monkeypatch.setattr(pipeline_module, "AsyncSessionLocal", db)

    second, _ = await execute(db, await create_run(db, source_id))

    assert second.records_created == 2, "previously failed items must not be counted as duplicates"
    assert second.records_deduplicated == 0
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(ExtractedRecord)) == 2  # no duplicate rows


# --- idempotency under concurrency -------------------------------------------

async def test_concurrent_runs_of_two_sources_do_not_duplicate_entities(db):
    run_a = await create_run(db, await create_source(db, slug="remotive-a"))
    run_b = await create_run(db, await create_source(db, slug="remotive-b"))

    (a, _), (b, _) = await asyncio.gather(execute(db, run_a), execute(db, run_b))

    assert a.status == b.status == RunStatus.COMPLETED.value
    assert a.records_created + b.records_created == 2  # each vacancy created exactly once
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Job)) == 2


# --- scheduler ----------------------------------------------------------------

def test_is_due():
    t = lambda h, m, s=0: datetime(2026, 11, 8, h, m, s, tzinfo=UTC)
    assert is_due("0 * * * *", None, t(10, 0, 30)) is True       # slot just passed
    assert is_due("0 * * * *", None, t(10, 5)) is False          # never scheduled: wait for next slot
    assert is_due("0 * * * *", t(10, 0, 5), t(10, 59)) is False  # already ran this hour
    assert is_due("0 * * * *", t(10, 0, 5), t(11, 0, 10)) is True


async def test_scheduler_starts_due_sources_once(db, queue):
    source_id = await create_source(db, schedule_cron="* * * * *")
    now = datetime.now(UTC) + timedelta(seconds=5)

    assert len(await dispatch_due_sources(sessionmaker=db, now=now)) == 1
    async with db() as s:
        run = await s.scalar(select(SourceRun).where(SourceRun.source_id == source_id))
    assert run.trigger_type == "SCHEDULED" and queue == [run.id]

    # Still active: the next tick must not start another run.
    assert await dispatch_due_sources(sessionmaker=db, now=now + timedelta(minutes=1)) == []

    await set_status(db, run.id, RunStatus.COMPLETED.value)
    assert await dispatch_due_sources(sessionmaker=db, now=now) == []  # same slot already served
    assert len(await dispatch_due_sources(sessionmaker=db, now=now + timedelta(minutes=2))) == 1


async def test_scheduler_skips_disabled_unconfigured_and_invalid_sources(db, queue):
    await create_source(db, schedule_cron="* * * * *", is_enabled=False)
    await create_source(db, schedule_cron="* * * * *", config_status="AWAITING_CONFIGURATION")
    await create_source(db, schedule_cron="not a cron")
    await create_source(db, schedule_cron=None)

    assert await dispatch_due_sources(sessionmaker=db, now=datetime.now(UTC) + timedelta(minutes=5)) == []
    assert queue == []


# --- reaper & event refresh ---------------------------------------------------

async def test_reaper_fails_only_stale_runs(db):
    long_ago = datetime.now(UTC) - timedelta(hours=8)
    stale_running = await create_run(db, await create_source(db), RunStatus.RUNNING.value, started_at=long_ago)
    fresh_running = await create_run(db, await create_source(db), RunStatus.RUNNING.value, started_at=datetime.now(UTC))
    stale_queued = await create_run(db, await create_source(db), RunStatus.QUEUED.value, created_at=long_ago)
    finished = await create_run(db, await create_source(db), RunStatus.COMPLETED.value, started_at=long_ago)

    assert await reap_stale_runs(sessionmaker=db) == 2

    assert (await get_run(db, stale_running)).status == RunStatus.FAILED.value
    assert (await get_run(db, stale_queued)).status == RunStatus.FAILED.value
    assert (await get_run(db, fresh_running)).status == RunStatus.RUNNING.value
    assert (await get_run(db, finished)).status == RunStatus.COMPLETED.value


async def test_event_statuses_follow_passing_deadlines(db):
    async with db() as s:
        s.add(Event(
            name="Old Hack", normalized_name="old hack", description="d",
            registration_url="https://example.com/old", source_url="https://example.com/old",
            registration_deadline=datetime.now(UTC) - timedelta(days=1),
            status="OPEN_REGISTRATION", source_platform="devpost",
        ))
        await s.commit()

    assert await refresh_event_statuses(sessionmaker=db) == 1
    async with db() as s:
        assert (await s.scalar(select(Event))).status == "REGISTRATION_CLOSED"
    assert await refresh_event_statuses(sessionmaker=db) == 0  # idempotent


# --- honest outcomes ------------------------------------------------------------

async def test_run_blocked_entirely_by_robots_txt_is_failed_not_completed(db):
    from app.modules.scraping.gateway import RobotsDisallowedError

    async def disallow(seed, n):
        raise RobotsDisallowedError(seed.url)

    run, _ = await execute(db, await create_run(db, await create_source(db)), make_gateway(on_fetch=disallow))

    assert run.status == RunStatus.FAILED.value
    assert run.pages_fetched == 0
    assert "robots.txt" in run.error_summary
