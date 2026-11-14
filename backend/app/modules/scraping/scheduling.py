"""
Periodic maintenance driven by Celery beat (see workers/celery_app.py):

  * dispatch_due_sources   – starts runs for sources whose `schedule_cron` is due
  * reap_stale_runs        – fails runs stuck in RUNNING/QUEUED after a worker crash or hard kill
  * refresh_event_statuses – recomputes event lifecycle status as deadlines pass

Each takes an optional sessionmaker and `now` so it can be tested deterministically.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from croniter import croniter
from sqlalchemy import func, select, update

from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.source import ConfigStatus, RunStatus, Source, SourceRun
from app.modules.scraping.runs import (
    QueueUnavailableError,
    RunAlreadyActiveError,
    RunTooSoonError,
    create_and_dispatch_run,
)

logger = logging.getLogger("radar.scraping.scheduling")

SCHEDULED_TRIGGER = "SCHEDULED"


def is_valid_cron(expr: Optional[str]) -> bool:
    if not expr:
        return False
    return bool(croniter.is_valid(expr))


def is_due(cron_expr: str, last_scheduled_at: Optional[datetime], now: datetime) -> bool:
    """
    Due when a cron slot has passed since the last scheduled run. A source that has never
    been scheduled starts at its next slot (base = one minute ago), not immediately.
    """
    base = last_scheduled_at or (now - timedelta(minutes=1))
    return croniter(cron_expr, base).get_next(datetime) <= now


async def dispatch_due_sources(
    sessionmaker: Callable = AsyncSessionLocal,
    now: Optional[datetime] = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    started: list[str] = []

    async with sessionmaker() as db:
        sources = (await db.scalars(
            select(Source).where(
                Source.is_enabled.is_(True),
                Source.schedule_cron.is_not(None),
                Source.config_status == ConfigStatus.READY.value,
            )
        )).all()

        for source in sources:
            if not is_valid_cron(source.schedule_cron):
                logger.warning("Source %s has invalid schedule_cron %r; skipping.", source.slug, source.schedule_cron)
                continue

            last_scheduled = await db.scalar(
                select(func.max(SourceRun.created_at)).where(
                    SourceRun.source_id == source.id, SourceRun.trigger_type == SCHEDULED_TRIGGER
                )
            )
            if not is_due(source.schedule_cron, last_scheduled, now):
                continue

            try:
                run = await create_and_dispatch_run(db, source, SCHEDULED_TRIGGER)
                started.append(source.slug)
                logger.info("Scheduled run %s started for %s (%s)", run.id, source.slug, source.schedule_cron)
            except RunAlreadyActiveError:
                logger.info("Skipping scheduled run for %s: a run is already active.", source.slug)
            except RunTooSoonError as exc:
                logger.info("Skipping scheduled run for %s: %s", source.slug, exc)
            except QueueUnavailableError:
                logger.error("Queue unavailable; scheduled run for %s marked failed.", source.slug)

    return started


async def reap_stale_runs(
    sessionmaker: Callable = AsyncSessionLocal,
    now: Optional[datetime] = None,
) -> int:
    """Fails runs that can no longer be progressing. Returns how many were reaped."""
    now = now or datetime.now(timezone.utc)
    running_cutoff = now - timedelta(seconds=settings.PIPELINE_TIME_LIMIT_SECONDS + 300)
    queued_cutoff = now - timedelta(seconds=settings.QUEUED_RUN_STALE_AFTER_SECONDS)

    async with sessionmaker() as db:
        running = await db.execute(
            update(SourceRun)
            .where(
                SourceRun.status == RunStatus.RUNNING.value,
                func.coalesce(SourceRun.started_at, SourceRun.created_at) < running_cutoff,
            )
            .values(
                status=RunStatus.FAILED.value,
                finished_at=now,
                error_summary="Run exceeded the pipeline time limit or its worker died; reaped.",
            )
        )
        queued = await db.execute(
            update(SourceRun)
            .where(SourceRun.status == RunStatus.QUEUED.value, SourceRun.created_at < queued_cutoff)
            .values(
                status=RunStatus.FAILED.value,
                finished_at=now,
                error_summary="Run was never picked up by a worker; reaped.",
            )
        )
        await db.commit()

    total = (running.rowcount or 0) + (queued.rowcount or 0)
    if total:
        logger.warning("Reaped %d stale run(s) (%d running, %d queued).", total, running.rowcount, queued.rowcount)
    return total


async def refresh_event_statuses(
    sessionmaker: Callable = AsyncSessionLocal,
    now: Optional[datetime] = None,
) -> int:
    """Event status is computed at ingest; recompute it so deadlines passing are reflected."""
    from app.models.event import Event, EventStatus
    from app.modules.events.services.event_classifier import compute_event_status

    now = now or datetime.now(timezone.utc)
    changed = 0
    async with sessionmaker() as db:
        events = (await db.scalars(
            select(Event).where(Event.status != EventStatus.COMPLETED.value)
        )).all()
        for event in events:
            new_status = compute_event_status(
                start_date=event.start_date,
                end_date=event.end_date,
                registration_deadline=event.registration_deadline,
                registration_opens_at=event.registration_opens_at,
                now=now,
            )
            new_value = getattr(new_status, "value", new_status)
            if new_value != event.status:
                event.status = new_value
                changed += 1
        await db.commit()
    if changed:
        logger.info("Refreshed lifecycle status for %d event(s).", changed)
    return changed
