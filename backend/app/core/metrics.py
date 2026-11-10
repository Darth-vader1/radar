"""
Prometheus metrics, served by the API at GET /metrics (internal network only; Caddy does
not route it publicly).

Two kinds:
  * HTTP metrics, recorded in-process by the API. With several uvicorn workers set
    PROMETHEUS_MULTIPROC_DIR (the Docker image does) so all processes are aggregated.
  * Pipeline / queue metrics, read from PostgreSQL and Redis at scrape time. They are
    correct no matter how many Celery workers run or where, and survive restarts.
"""
import logging
import os
import time
from collections.abc import Mapping
from typing import Any, Iterable, Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, InfoMetricFamily
from prometheus_client.registry import Collector

from app.core.config import settings

logger = logging.getLogger("radar.metrics")

MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if MULTIPROC_DIR:
    # Metric objects below write here; make sure it exists in any process importing this.
    os.makedirs(MULTIPROC_DIR, exist_ok=True)

HTTP_REQUESTS = Counter(
    "radar_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "radar_http_request_duration_seconds",
    "API request latency.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

FINISHED_STATUSES = ("COMPLETED", "PARTIAL_FAILURE", "FAILED", "CANCELLED")


def route_label(scope: Mapping[str, Any]) -> str:
    """
    Full route template (e.g. /api/v1/tasks/runs/{run_id}) so labels stay low-cardinality.

    FastAPI >= 0.116 reports the matched route's path relative to its own router
    (/tasks/runs/{run_id}), without the prefixes of the routers it is included in. The
    static prefix is recovered by rendering the route with this request's path params and
    taking what precedes it in the real path; actual parameter values never reach a label.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "unmatched"
    path = scope.get("path", "")
    try:
        rendered = getattr(route, "path_format", template).format(**(scope.get("path_params") or {}))
    except (KeyError, IndexError, ValueError):
        return template
    if rendered and path.endswith(rendered):
        return path[: len(path) - len(rendered)] + template
    return template


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


class _StaticCollector(Collector):
    def __init__(self, families: list):
        self._families = families

    def collect(self) -> Iterable:
        return iter(self._families)


async def _pipeline_families() -> list:
    """Reads run, record, dead-letter, queue and worker state. Failures degrade to a gauge."""
    from sqlalchemy import func, select

    from app.database.session import AsyncSessionLocal
    from app.models.source import DeadLetterTask, ScrapingTask, Source, SourceRun

    families: list = []
    up = GaugeMetricFamily("radar_metrics_db_up", "1 if pipeline metrics could be read from PostgreSQL.")
    try:
        async with AsyncSessionLocal() as db:
            slugs: dict[Any, str] = {row[0]: row[1] for row in (await db.execute(select(Source.id, Source.slug))).all()}

            finished = CounterMetricFamily(
                "radar_runs_finished", "Source runs that reached a final status.", labels=["source", "status"]
            )
            active = GaugeMetricFamily("radar_runs_active", "Queued or running source runs.", labels=["source", "status"])
            rows = await db.execute(
                select(SourceRun.source_id, SourceRun.status, func.count()).group_by(SourceRun.source_id, SourceRun.status)
            )
            for source_id, status, count in rows.all():
                labels = [slugs.get(source_id, "unknown"), status]
                (finished if status in FINISHED_STATUSES else active).add_metric(labels, count)
            families += [finished, active]

            records = CounterMetricFamily(
                "radar_records_collected", "Canonical records created per source.", labels=["source"]
            )
            last_success = GaugeMetricFamily(
                "radar_source_last_success_timestamp_seconds",
                "Unix time of each source's last successful run (alert when this gets old).",
                labels=["source"],
            )
            for slug, total, last in (await db.execute(
                select(Source.slug, Source.total_records_collected, Source.last_success_at)
            )).all():
                records.add_metric([slug], total or 0)
                if last is not None:
                    last_success.add_metric([slug], last.timestamp())
            families += [records, last_success]

            failures = CounterMetricFamily(
                "radar_task_failures", "Failed pipeline steps (fetch/extract/discover).", labels=["source", "stage"]
            )
            for source_id, stage, count in (await db.execute(
                select(ScrapingTask.source_id, ScrapingTask.stage, func.count())
                .where(ScrapingTask.status == "FAILED")
                .group_by(ScrapingTask.source_id, ScrapingTask.stage)
            )).all():
                failures.add_metric([slugs.get(source_id, "unknown"), stage], count)
            families.append(failures)

            dlq = GaugeMetricFamily("radar_dead_letter_unresolved", "Unresolved dead-letter items.")
            dlq.add_metric([], await db.scalar(
                select(func.count()).select_from(DeadLetterTask).where(DeadLetterTask.resolved_at.is_(None))
            ) or 0)
            families.append(dlq)
        up.add_metric([], 1)
    except Exception as exc:
        logger.warning("Could not read pipeline metrics from the database: %s", type(exc).__name__)
        up.add_metric([], 0)
    families.append(up)
    families += await _queue_families()
    return families


async def _queue_families() -> list:
    import redis.asyncio as aioredis

    from app.core.heartbeat import count_live_workers

    queue = GaugeMetricFamily("radar_celery_queue_length", "Tasks waiting in the Celery queue.", labels=["queue"])
    workers = GaugeMetricFamily("radar_workers_alive", "Celery workers with a fresh heartbeat.")
    broker_up = GaugeMetricFamily("radar_metrics_broker_up", "1 if the Celery broker could be read.")
    try:
        client = aioredis.from_url(settings.CELERY_BROKER_URL, socket_timeout=2.0, socket_connect_timeout=2.0)
        try:
            queue.add_metric(["celery"], await client.llen("celery"))
        finally:
            await client.aclose()
        workers.add_metric([], await count_live_workers())
        broker_up.add_metric([], 1)
        return [queue, workers, broker_up]
    except Exception as exc:
        logger.warning("Could not read queue metrics from the broker: %s", type(exc).__name__)
        broker_up.add_metric([], 0)
        return [broker_up]


async def render_metrics() -> tuple[bytes, str]:
    registry = CollectorRegistry()
    if MULTIPROC_DIR:
        from prometheus_client import multiprocess

        multiprocess.MultiProcessCollector(registry)
    else:
        registry.register(_HttpCollector())

    info = InfoMetricFamily("radar_build", "Build and environment information.")
    info.add_metric([], {"release": settings.APP_RELEASE or "unknown", "environment": settings.ENVIRONMENT})
    registry.register(_StaticCollector([info, *(await _pipeline_families())]))
    return generate_latest(registry), CONTENT_TYPE_LATEST


class _HttpCollector(Collector):
    """Exposes the module-level HTTP metrics when not in multiprocess mode."""

    def collect(self) -> Iterable:
        yield from HTTP_REQUESTS.collect()
        yield from HTTP_LATENCY.collect()


def check_metrics_token(authorization: Optional[str]) -> bool:
    if not settings.METRICS_TOKEN:
        return True
    import secrets

    if not authorization:
        return False
    return secrets.compare_digest(authorization, f"Bearer {settings.METRICS_TOKEN}")


def monotonic() -> float:
    return time.perf_counter()
