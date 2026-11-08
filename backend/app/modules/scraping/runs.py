"""
Creating and dispatching SourceRuns. Shared by the manual trigger API, dead-letter
retries and the cron scheduler so they all follow the same rules:

  * at most one QUEUED/RUNNING run per source (enforced by a partial unique index, so
    two concurrent triggers cannot both win);
  * runs only ever execute on Celery workers, never inside the API process;
  * if the queue is unreachable the run is marked FAILED immediately instead of sitting
    in QUEUED forever.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.source import RunStatus, Source, SourceRun

logger = logging.getLogger("radar.scraping.runs")

ACTIVE_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
ACTIVE_RUN_INDEX = "uq_source_runs_one_active_per_source"


class RunAlreadyActiveError(Exception):
    def __init__(self, source: Source, active_run_id: Optional[uuid.UUID] = None):
        self.source = source
        self.active_run_id = active_run_id
        super().__init__(f"Source '{source.slug}' already has a queued or running run.")


class QueueUnavailableError(Exception):
    """The Celery broker could not accept the task."""


async def find_active_run(db: AsyncSession, source_id: uuid.UUID) -> Optional[SourceRun]:
    return await db.scalar(
        select(SourceRun).where(SourceRun.source_id == source_id, SourceRun.status.in_(ACTIVE_STATUSES))
    )


async def enqueue_run(run_id: uuid.UUID) -> str:
    """Publishes the pipeline task. Raises QueueUnavailableError instead of hanging."""
    from workers.tasks import run_pipeline  # local import: workers imports app, not vice versa

    def _publish() -> str:
        # retry=False: fail fast; the caller decides what to do with the run.
        return run_pipeline.apply_async(args=[str(run_id)], retry=False).id

    try:
        return await asyncio.wait_for(asyncio.to_thread(_publish), timeout=settings.TASK_DISPATCH_TIMEOUT_SECONDS)
    except Exception as exc:  # broker down, DNS failure, timeout...
        raise QueueUnavailableError(f"{type(exc).__name__}: {exc}") from exc


async def create_and_dispatch_run(
    db: AsyncSession,
    source: Source,
    trigger_type: str,
    search_params: Optional[dict[str, Any]] = None,
    triggered_by_user_id: Optional[uuid.UUID] = None,
) -> SourceRun:
    existing = await find_active_run(db, source.id)
    if existing is not None:
        raise RunAlreadyActiveError(source, existing.id)

    run = SourceRun(
        id=uuid.uuid4(),
        source_id=source.id,
        triggered_by_user_id=triggered_by_user_id,
        trigger_type=trigger_type,
        status=RunStatus.QUEUED.value,
        search_params=search_params or {},
    )
    db.add(run)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if ACTIVE_RUN_INDEX in str(exc.orig):
            raise RunAlreadyActiveError(source) from exc
        raise

    try:
        task_id = await enqueue_run(run.id)
        logger.info("Dispatched SourceRun %s (%s) as Celery task %s", run.id, trigger_type, task_id)
    except QueueUnavailableError as exc:
        logger.error("Task queue unavailable; failing SourceRun %s: %s", run.id, exc)
        await db.execute(
            update(SourceRun)
            .where(SourceRun.id == run.id, SourceRun.status == RunStatus.QUEUED.value)
            .values(
                status=RunStatus.FAILED.value,
                finished_at=datetime.now(timezone.utc),
                error_summary="Task queue unavailable; the run was not started.",
            )
        )
        await db.commit()
        raise

    await db.refresh(run)
    return run
