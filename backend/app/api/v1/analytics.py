"""
Analytics: how collection changes over time and how each crawler is doing.

Complements /insights (a snapshot of what is in the data now). All values are SQL aggregates;
days are UTC calendar days.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1.events import INACTIVE_STATUSES
from app.api.v1.insights import INACTIVE_JOB_STATUSES
from app.models.auth import User
from app.models.business import Business
from app.models.event import Event
from app.models.job import Job, RemoteStatus
from app.models.source import DeadLetterTask, RunStatus, Source, SourceRun
from app.schemas.analytics import (
    AnalyticsResponse,
    DailyDiscoveries,
    DailyRuns,
    Geography,
    SourceDiscoveries,
    SourceHealth,
    WeeklyPrizes,
)
from app.schemas.insights import NamedCount

router = APIRouter(prefix="/analytics", tags=["Analytics"])

FINISHED = (RunStatus.COMPLETED.value, RunStatus.PARTIAL_FAILURE.value, RunStatus.FAILED.value)
PRIZE_WEEKS = 12
NIGERIA = "nigeria"
# Job boards put these in the country field; they mean "no fixed country", not a place.
NOT_A_COUNTRY = ("worldwide", "remote", "worldwide remote", "anywhere", "global", "international")


def utc_day(column: Any) -> Any:
    return func.date(func.timezone("UTC", column))


def day_range(start: date, end: date) -> List[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def _discoveries(db: AsyncSession, since: datetime, start: date, end: date) -> List[DailyDiscoveries]:
    per_day: Dict[date, DailyDiscoveries] = {d: DailyDiscoveries(date=d) for d in day_range(start, end)}
    for model, field in ((Job, "jobs"), (Event, "events"), (Business, "businesses")):
        day = utc_day(model.discovered_at)
        rows = await db.execute(
            select(day, func.count(model.id)).where(model.discovered_at >= since).group_by(day)
        )
        for d, n in rows.all():
            if d in per_day:
                setattr(per_day[d], field, int(n))
    return list(per_day.values())


async def _discoveries_by_source(db: AsyncSession, since: datetime) -> List[SourceDiscoveries]:
    out: List[SourceDiscoveries] = []
    for model, entity in ((Job, "JOB"), (Event, "EVENT"), (Business, "BUSINESS")):
        name = func.coalesce(Source.name, "Unknown source").label("source")
        rows = await db.execute(
            select(name, func.count(model.id))
            .select_from(model)
            .outerjoin(Source, Source.id == model.primary_source_id)
            .where(model.discovered_at >= since)
            .group_by(name)
        )
        out += [SourceDiscoveries(source=s, entity_type=entity, count=int(n)) for s, n in rows.all()]
    return sorted(out, key=lambda x: (-x.count, x.source))


async def _runs(db: AsyncSession, since: datetime, start: date, end: date) -> List[DailyRuns]:
    per_day: Dict[date, DailyRuns] = {d: DailyRuns(date=d) for d in day_range(start, end)}
    run_time = func.coalesce(SourceRun.started_at, SourceRun.created_at)
    day = utc_day(run_time)
    rows = await db.execute(
        select(day, SourceRun.status, func.count(SourceRun.id))
        .where(run_time >= since, SourceRun.status.in_(FINISHED))
        .group_by(day, SourceRun.status)
    )
    field = {
        RunStatus.COMPLETED.value: "completed",
        RunStatus.PARTIAL_FAILURE.value: "partial",
        RunStatus.FAILED.value: "failed",
    }
    for d, status, n in rows.all():
        if d in per_day:
            setattr(per_day[d], field[status], int(n))
    return list(per_day.values())


async def _source_health(db: AsyncSession, since: datetime) -> List[SourceHealth]:
    run_time = func.coalesce(SourceRun.started_at, SourceRun.created_at)
    finished = SourceRun.status.in_(FINISHED)

    def count_status(*statuses: str) -> Any:
        return func.count(case((SourceRun.status.in_(statuses), 1)))

    duration = func.extract("epoch", SourceRun.finished_at - SourceRun.started_at)
    stats = {
        row.source_id: row
        for row in (
            await db.execute(
                select(
                    SourceRun.source_id,
                    func.count(SourceRun.id).label("runs"),
                    count_status(RunStatus.COMPLETED.value).label("completed"),
                    count_status(RunStatus.PARTIAL_FAILURE.value).label("partial"),
                    count_status(RunStatus.FAILED.value).label("failed"),
                    func.avg(case((finished, duration))).label("avg_duration"),
                    func.avg(case((finished, SourceRun.records_created))).label("avg_created"),
                )
                .where(run_time >= since)
                .group_by(SourceRun.source_id)
            )
        ).all()
    }
    # Most recent run per source (any age), so idle sources still show when they last ran.
    latest_rank = func.row_number().over(partition_by=SourceRun.source_id, order_by=desc(run_time)).label("rk")
    latest_sq = select(SourceRun.source_id, run_time.label("at"), SourceRun.status, latest_rank).subquery()
    latest = {
        sid: (at, status)
        for sid, at, status in (
            await db.execute(select(latest_sq.c.source_id, latest_sq.c.at, latest_sq.c.status).where(latest_sq.c.rk == 1))
        ).all()
    }
    # Latest run that recorded an error: the source row's own error fields are often empty.
    err_time = func.coalesce(SourceRun.finished_at, run_time)
    err_rank = func.row_number().over(partition_by=SourceRun.source_id, order_by=desc(err_time)).label("rk")
    err_sq = (
        select(SourceRun.source_id, err_time.label("at"), SourceRun.error_summary, err_rank)
        .where(func.coalesce(SourceRun.error_summary, "") != "")
        .subquery()
    )
    run_errors = {
        sid: (at, msg)
        for sid, at, msg in (
            await db.execute(select(err_sq.c.source_id, err_sq.c.at, err_sq.c.error_summary).where(err_sq.c.rk == 1))
        ).all()
    }
    dlq_rows = await db.execute(
        select(DeadLetterTask.source_id, func.count(DeadLetterTask.id))
        .where(DeadLetterTask.resolved_at.is_(None))
        .group_by(DeadLetterTask.source_id)
    )
    open_dlq: Dict[Any, int] = {sid: int(n) for sid, n in dlq_rows.all()}

    out: List[SourceHealth] = []
    for src in (await db.scalars(select(Source).order_by(Source.module_type, Source.name))).all():
        st = stats.get(src.id)
        done = (st.completed + st.partial + st.failed) if st else 0
        last_at, last_status = latest.get(src.id, (None, None))
        err_at, err_msg = run_errors.get(src.id, (None, None))
        if src.last_error_message and (err_at is None or (src.last_error_at and src.last_error_at >= err_at)):
            err_at, err_msg = src.last_error_at, src.last_error_message
        out.append(
            SourceHealth(
                id=src.id,
                name=src.name,
                module_type=src.module_type,
                is_enabled=src.is_enabled,
                runs=st.runs if st else 0,
                completed=st.completed if st else 0,
                partial=st.partial if st else 0,
                failed=st.failed if st else 0,
                # A partial failure still collected data, so it counts as half a success.
                success_rate_pct=round(100 * (st.completed + 0.5 * st.partial) / done, 1) if st and done else None,
                avg_duration_seconds=round(float(st.avg_duration), 1) if st and st.avg_duration is not None else None,
                avg_records_created=round(float(st.avg_created), 1) if st and st.avg_created is not None else None,
                last_run_at=last_at,
                last_run_status=last_status,
                last_error_at=err_at,
                last_error_message=(err_msg or "")[:300] or None,
                open_failed_tasks=int(open_dlq.get(src.id, 0)),
                total_records_collected=src.total_records_collected,
            )
        )
    return out


async def _top(db: AsyncSession, column: Any, fallback: str, *where: Any, limit: int = 10) -> List[NamedCount]:
    label = func.coalesce(func.nullif(func.trim(column), ""), fallback).label("name")
    return await _count_by(db, label, *where, limit=limit)


async def _count_by(db: AsyncSession, label: Any, *where: Any, limit: int = 10) -> List[NamedCount]:
    n = func.count().label("n")
    rows = await db.execute(select(label, n).where(*where).group_by(label).order_by(desc("n"), label).limit(limit))
    return [NamedCount(name=name, count=int(c)) for name, c in rows.all()]


async def _geography(db: AsyncSession) -> Geography:
    active_job = Job.status.not_in(INACTIVE_JOB_STATUSES)
    total = await db.scalar(select(func.count(Job.id)).where(active_job)) or 0
    remote = await db.scalar(
        select(func.count(Job.id)).where(active_job, Job.remote_status == RemoteStatus.REMOTE.value)
    ) or 0
    country = func.nullif(func.trim(Job.country), "")
    job_country = case(
        (country.is_(None), "Not stated"),
        (func.lower(country).in_(NOT_A_COUNTRY), "Anywhere"),
        else_=country,
    )
    nigeria = await db.scalar(select(func.count(Job.id)).where(active_job, func.lower(Job.country) == NIGERIA)) or 0
    return Geography(
        jobs_by_country=await _count_by(db, job_country.label("name"), active_job),
        jobs_remote=remote,
        jobs_total=total,
        nigeria_jobs=nigeria,
        businesses_by_city=await _top(db, Business.city, "Not stated"),
        events_by_mode=await _top(db, Event.delivery_mode, "UNSPECIFIED", Event.status.not_in(INACTIVE_STATUSES)),
    )


async def _prizes(db: AsyncSession, now: datetime) -> List[WeeklyPrizes]:
    """Estimated prize money of open events, grouped by the week their registration closes."""
    week = func.date(func.date_trunc("week", func.timezone("UTC", Event.registration_deadline)))
    rows = await db.execute(
        select(week, func.coalesce(func.sum(Event.prize_amount_usd_est), 0), func.count(Event.id))
        .where(
            Event.status.not_in(INACTIVE_STATUSES),
            Event.registration_deadline >= now,
            Event.registration_deadline < now + timedelta(weeks=PRIZE_WEEKS),
        )
        .group_by(week)
    )
    found = {w: (float(p), int(n)) for w, p, n in rows.all()}
    first = now.date() - timedelta(days=now.weekday())  # Monday, matching Postgres date_trunc('week')
    weeks = [first + timedelta(weeks=i) for i in range(PRIZE_WEEKS)]
    by_week: Dict[date, tuple] = defaultdict(lambda: (0.0, 0), found)
    return [WeeklyPrizes(week_start=w, prize_usd=by_week[w][0], events=by_week[w][1]) for w in weeks]


@router.get("", response_model=AnalyticsResponse)
async def get_analytics(
    days: int = Query(30, ge=7, le=180, description="How many days of history to include"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnalyticsResponse:
    """Discoveries and crawler runs over time, per-source health, geography and upcoming prize money."""
    now = datetime.now(timezone.utc)
    end = now.date()
    start = end - timedelta(days=days - 1)
    since = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    return AnalyticsResponse(
        generated_at=now,
        days=days,
        discoveries=await _discoveries(db, since, start, end),
        discoveries_by_source=await _discoveries_by_source(db, since),
        runs=await _runs(db, since, start, end),
        source_health=await _source_health(db, since),
        geography=await _geography(db),
        prizes_by_deadline_week=await _prizes(db, now),
    )
