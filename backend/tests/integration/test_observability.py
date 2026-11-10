"""
Phase 6: request ids, access logs, Prometheus metrics, readiness, worker heartbeats,
Sentry scrubbing and run-scoped pipeline log context.
"""
import asyncio
import logging
import re
import uuid

import pytest
from test_run_lifecycle import create_run, create_source, execute

from app.core import heartbeat
from app.core.config import settings
from app.core.logging import ContextFilter
from app.core.observability import _before_send, init_sentry
from app.database import session as session_module
from app.models.source import RunStatus

pytestmark = pytest.mark.integration

API = settings.API_V1_PREFIX
TEST_REDIS = re.sub(r"/\d+$", "/15", settings.REDIS_URL)  # isolated Redis db for heartbeat tests


class Capture(logging.Handler):
    """Captures records with the log context applied, as the real handler would."""

    def __init__(self):
        super().__init__()
        self.addFilter(ContextFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def capture():
    handlers = []

    def attach(logger_name):
        h = Capture()
        lg = logging.getLogger(logger_name)
        lg.addHandler(h)
        handlers.append((lg, h))
        return h

    yield attach
    for lg, h in handlers:
        lg.removeHandler(h)


@pytest.fixture
def metrics_db(db_sessionmaker, monkeypatch):
    """Point the /metrics database reads at the test database."""
    monkeypatch.setattr(session_module, "AsyncSessionLocal", db_sessionmaker)
    return db_sessionmaker


# --- request ids & access log --------------------------------------------------

async def test_request_id_is_generated_and_returned(client, capture):
    access = capture("radar.access")
    r = await client.get(f"{API}/health/ready")

    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", rid)
    line = next(rec for rec in access.records if rec.http_path == f"{API}/health/ready")
    assert line.request_id == rid
    assert line.http_status == r.status_code and line.duration_ms >= 0
    assert line.http_route == f"{API}/health/ready"


async def test_well_formed_incoming_request_id_is_kept(client):
    r = await client.get(f"{API}/health/live", headers={"X-Request-ID": "proxy-abc.123"})
    assert r.headers["x-request-id"] == "proxy-abc.123"


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "inj\r\nected", "<script>"])
async def test_malformed_incoming_request_id_is_replaced(client, bad):
    r = await client.get(f"{API}/health/live", headers={"X-Request-ID": bad})
    assert r.headers["x-request-id"] != bad
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])


# --- metrics ---------------------------------------------------------------------

async def test_metrics_expose_pipeline_and_http_series(client, db, metrics_db):
    source_id = await create_source(db, slug="metrics-src")
    await create_run(db, source_id, RunStatus.COMPLETED.value)
    await create_run(db, source_id, RunStatus.FAILED.value)
    await create_run(db, source_id, RunStatus.QUEUED.value)
    await client.get(f"{API}/tasks/runs/{uuid.uuid4()}")  # templated route, 401 without auth

    r = await client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text

    assert 'radar_runs_finished_total{source="metrics-src",status="COMPLETED"} 1.0' in body
    assert 'radar_runs_finished_total{source="metrics-src",status="FAILED"} 1.0' in body
    assert 'radar_runs_active{source="metrics-src",status="QUEUED"} 1.0' in body
    assert "radar_dead_letter_unresolved 0.0" in body
    assert "radar_metrics_db_up 1.0" in body
    assert "radar_metrics_broker_up 1.0" in body
    assert "radar_celery_queue_length" in body and "radar_workers_alive" in body
    assert 'route="/api/v1/tasks/runs/{run_id}"' in body  # template, not the raw UUID path
    assert "radar_http_request_duration_seconds_bucket" in body
    assert 'radar_build_info{environment=' in body


async def test_metrics_report_db_down_instead_of_failing(client, monkeypatch):
    def broken_session():
        raise ConnectionError("db down")

    monkeypatch.setattr(session_module, "AsyncSessionLocal", broken_session)
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "radar_metrics_db_up 0.0" in r.text


async def test_metrics_token_is_enforced_when_configured(client, metrics_db, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    assert (await client.get("/metrics")).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 401
    assert (await client.get("/metrics", headers={"Authorization": "Bearer s3cret-token"})).status_code == 200


async def test_metrics_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_ENABLED", False)
    assert (await client.get("/metrics")).status_code == 404


# --- readiness -------------------------------------------------------------------

async def test_readiness_checks_broker_and_reports_workers(client):
    r = await client.get(f"{API}/health/ready")
    body = r.json()
    assert r.status_code == 200 and body["ready"] is True
    assert body["checks"]["broker"] is True
    assert isinstance(body["checks"]["workers_alive"], int)


async def test_readiness_failure_does_not_leak_error_details(client, monkeypatch):
    monkeypatch.setattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6399/1")  # nothing listens
    r = await client.get(f"{API}/health/ready")

    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False and body["checks"]["broker"] is False
    text = r.text.lower()
    for leak in ("error", "refused", "6399", "traceback", "connect"):
        assert leak not in text


# --- worker heartbeat ------------------------------------------------------------

async def test_worker_heartbeat_is_counted_and_removed_on_shutdown():
    import redis.asyncio as aioredis

    client = aioredis.from_url(TEST_REDIS)
    await client.delete(*[k async for k in client.scan_iter(match=f"{heartbeat.KEY_PREFIX}*")] or ["_none_"])
    await client.aclose()

    heartbeat.start_worker_heartbeat("celery@test-host", redis_url=TEST_REDIS)
    try:
        for _ in range(40):
            if await heartbeat.count_live_workers(TEST_REDIS) == 1:
                break
            await asyncio.sleep(0.05)
        assert await heartbeat.count_live_workers(TEST_REDIS) == 1
    finally:
        await asyncio.to_thread(heartbeat.stop_worker_heartbeat)
    assert await heartbeat.count_live_workers(TEST_REDIS) == 0


# --- sentry ----------------------------------------------------------------------

def test_sentry_is_off_without_dsn(monkeypatch):
    monkeypatch.setattr(settings, "SENTRY_DSN", None)
    assert init_sentry("api") is False


def test_sentry_events_are_scrubbed_and_tagged():
    from app.core.logging import log_context

    event = {
        "request": {
            "headers": {"Authorization": "Bearer t", "Cookie": "radar_access=x", "X-API-Key": "k", "Accept": "json"},
            "cookies": {"radar_access": "x"},
            "data": {"password": "p"},
        }
    }
    with log_context(request_id="req-7", run_id="run-3"):
        out = _before_send(event, {})

    headers = out["request"]["headers"]
    assert headers["Authorization"] == headers["Cookie"] == headers["X-API-Key"] == "[Filtered]"
    assert headers["Accept"] == "json"
    assert "cookies" not in out["request"] and "data" not in out["request"]
    assert out["tags"]["request_id"] == "req-7" and out["tags"]["run_id"] == "run-3"


# --- pipeline log context ----------------------------------------------------------

async def test_pipeline_logs_carry_run_id_and_source(db, capture):
    pipeline_logs = capture("radar.scraping.pipeline")
    run_id = await create_run(db, await create_source(db, slug="ctx-src"))

    await execute(db, run_id)

    assert pipeline_logs.records, "pipeline should log"
    assert all(rec.run_id == str(run_id) for rec in pipeline_logs.records)
    assert any(rec.source == "ctx-src" for rec in pipeline_logs.records)
