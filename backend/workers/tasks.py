import asyncio
import logging
import uuid
from typing import Awaitable, Callable, TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

from app.database.session import async_engine
from app.modules.scraping.pipeline import PipelineOrchestrator
from workers.celery_app import celery_app

logger = logging.getLogger("radar.workers.tasks")

T = TypeVar("T")

# Infrastructure hiccups worth retrying. Pipeline-level failures are recorded on the run
# itself (FAILED / PARTIAL_FAILURE + dead-letter rows) and are not retried here.
TRANSIENT_ERRORS = (OperationalError, DBAPIError, ConnectionError, TimeoutError)


def run_async(coro_factory: Callable[[], Awaitable[T]]) -> T:
    """
    Runs a coroutine on a fresh event loop. The async DB pool is disposed afterwards:
    pooled asyncpg connections are bound to the loop that created them and would break
    the next task (which gets a new loop) in the same worker process.
    """
    async def _wrapper() -> T:
        try:
            return await coro_factory()
        finally:
            await async_engine.dispose()

    return asyncio.run(_wrapper())


@celery_app.task(
    bind=True,
    name="tasks.run_pipeline",
    autoretry_for=TRANSIENT_ERRORS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_pipeline(self, source_run_id: str):
    """
    Executes the discovery pipeline for a SourceRun. Safe to deliver more than once:
    the orchestrator atomically claims the run and skips runs that are no longer active.
    """
    logger.info("Executing pipeline for SourceRun %s (task_id=%s, attempt=%d)",
                source_run_id, self.request.id, self.request.retries + 1)
    run_uuid = uuid.UUID(source_run_id)
    run_async(lambda: PipelineOrchestrator().execute_run(run_uuid))
    return {"status": "DONE", "source_run_id": source_run_id}


@celery_app.task(name="tasks.dispatch_scheduled_sources")
def dispatch_scheduled_sources():
    from app.modules.scraping.scheduling import dispatch_due_sources
    started = run_async(dispatch_due_sources)
    return {"started": started}


@celery_app.task(name="tasks.reap_stale_runs")
def reap_stale_runs():
    from app.modules.scraping.scheduling import reap_stale_runs as reap
    return {"reaped": run_async(reap)}


@celery_app.task(name="tasks.refresh_event_statuses")
def refresh_event_statuses():
    from app.modules.scraping.scheduling import refresh_event_statuses as refresh
    return {"updated": run_async(refresh)}


@celery_app.task(name="tasks.healthcheck")
def worker_healthcheck():
    return {"status": "ok", "worker": "celery"}
