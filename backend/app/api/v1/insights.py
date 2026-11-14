"""
Rule-based insights: plain aggregates over the jobs, events and businesses RADAR has collected.

Nothing here calls an AI model. Every number is a SQL aggregate and every highlight sentence
comes from a fixed template, so the page is free to run and always explainable.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import desc, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.v1.events import CLOSING_SOON_WINDOW, INACTIVE_STATUSES
from app.models.auth import User
from app.models.business import Business, WebsiteStatus
from app.models.event import Event
from app.models.job import Job, JobSkill, JobStatus, RemoteStatus
from app.schemas.insights import (
    BusinessInsights,
    DataFreshness,
    EventInsights,
    InsightsResponse,
    JobInsights,
    NamedCount,
    TopLead,
    UpcomingDeadline,
)

router = APIRouter(prefix="/insights", tags=["Insights"])

INACTIVE_JOB_STATUSES = (JobStatus.EXPIRED.value, JobStatus.FILLED.value)
TOP_N = 10


def pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _label(value: str) -> str:
    return value.replace("_", " ").lower()


async def _grouped(db: AsyncSession, column: Any, *where: Any) -> Dict[str, int]:
    rows = await db.execute(select(column, func.count()).where(*where).group_by(column))
    return {str(k): int(v) for k, v in rows.all() if k is not None}


async def _job_insights(db: AsyncSession, now: datetime) -> JobInsights:
    active = Job.status.not_in(INACTIVE_JOB_STATUSES)
    total = await db.scalar(select(func.count(Job.id)).where(active)) or 0
    new_7d = await db.scalar(
        select(func.count(Job.id)).where(active, Job.discovered_at >= now - timedelta(days=7))
    ) or 0
    with_salary = await db.scalar(
        select(func.count(Job.id)).where(active, (Job.salary_min.is_not(None)) | (Job.salary_max.is_not(None)))
    ) or 0

    # Count jobs (not mentions) per skill, grouped on the normalised name.
    skill_jobs = func.count(distinct(JobSkill.job_id)).label("jobs")
    skill_rows = await db.execute(
        select(func.min(JobSkill.skill_name), skill_jobs)
        .join(Job, Job.id == JobSkill.job_id)
        .where(active)
        .group_by(JobSkill.normalized_skill)
        .order_by(desc("jobs"), func.min(JobSkill.skill_name))
        .limit(TOP_N)
    )
    company_count = func.count(Job.id).label("n")
    company_rows = await db.execute(
        select(Job.company_name, company_count)
        .where(active)
        .group_by(Job.company_name)
        .order_by(desc("n"), Job.company_name)
        .limit(TOP_N)
    )
    by_remote = await _grouped(db, Job.remote_status, active)
    return JobInsights(
        total_active=total,
        new_last_7_days=new_7d,
        remote_share_pct=pct(by_remote.get(RemoteStatus.REMOTE.value, 0), total),
        with_salary_pct=pct(with_salary, total),
        top_skills=[NamedCount(name=n, count=c) for n, c in skill_rows.all()],
        top_companies=[NamedCount(name=n, count=c) for n, c in company_rows.all()],
        by_remote_status=by_remote,
        by_experience=await _grouped(db, Job.experience_level, active),
        by_category=await _grouped(db, Job.category, active),
    )


async def _event_insights(db: AsyncSession, now: datetime) -> EventInsights:
    active = Event.status.not_in(INACTIVE_STATUSES)
    future_deadline = (Event.registration_deadline.is_not(None), Event.registration_deadline >= now)
    total = await db.scalar(select(func.count(Event.id)).where(active)) or 0
    closing = await db.scalar(
        select(func.count(Event.id)).where(
            active, *future_deadline, Event.registration_deadline <= now + CLOSING_SOON_WINDOW
        )
    ) or 0
    prize = await db.scalar(select(func.coalesce(func.sum(Event.prize_amount_usd_est), 0)).where(active)) or 0
    upcoming = await db.scalars(
        select(Event).where(active, *future_deadline).order_by(Event.registration_deadline).limit(5)
    )
    return EventInsights(
        total_active=total,
        closing_within_7_days=closing,
        total_prize_usd=float(prize),
        next_deadlines=[
            UpcomingDeadline(
                id=e.id, name=e.name, organizer=e.organizer, deadline=e.registration_deadline,
                prize_summary=e.prize_summary, url=e.registration_url,
            )
            for e in upcoming.all()
            if e.registration_deadline is not None
        ],
        by_type=await _grouped(db, Event.event_type, active),
        by_delivery_mode=await _grouped(db, Event.delivery_mode, active),
    )


async def _business_insights(db: AsyncSession) -> BusinessInsights:
    total = await db.scalar(select(func.count(Business.id))) or 0
    avg_score = await db.scalar(select(func.avg(Business.lead_score))) or 0
    no_site = await db.scalar(
        select(func.count(Business.id)).where(Business.website_status == WebsiteStatus.NO_WEBSITE_FOUND.value)
    ) or 0
    leads = await db.scalars(select(Business).order_by(desc(Business.lead_score), Business.name).limit(5))
    cat_count = func.count(Business.id).label("n")
    cat_rows = await db.execute(
        select(Business.category, cat_count)
        .where(Business.category.is_not(None))
        .group_by(Business.category)
        .order_by(desc("n"), Business.category)
        .limit(8)
    )
    return BusinessInsights(
        total=total,
        avg_lead_score=round(float(avg_score), 1),
        no_website_count=no_site,
        top_leads=[
            TopLead(
                id=b.id, name=b.name, category=b.category, city=b.city, lead_score=b.lead_score,
                has_phone=bool(b.phone_number), website_status=b.website_status,
            )
            for b in leads.all()
        ],
        by_city=await _grouped(db, Business.city),
        top_categories=[NamedCount(name=n, count=c) for n, c in cat_rows.all()],
    )


def build_highlights(jobs: JobInsights, events: EventInsights, businesses: BusinessInsights) -> List[str]:
    """Plain-language observations from fixed templates; each one is skipped when its data is missing."""
    out: List[str] = []
    if jobs.total_active and jobs.top_skills:
        top = jobs.top_skills[0]
        out.append(
            f"{top.name} is the most requested skill, listed in {pct(top.count, jobs.total_active):g}% "
            f"of active jobs ({top.count:,} of {jobs.total_active:,})."
        )
    if jobs.total_active:
        out.append(f"{jobs.remote_share_pct:g}% of active jobs are fully remote.")
        if jobs.with_salary_pct == 0:
            out.append("None of the active jobs publish a salary range.")
        elif jobs.with_salary_pct < 50:
            out.append(f"Only {jobs.with_salary_pct:g}% of active jobs publish a salary range.")
    if jobs.new_last_7_days:
        out.append(f"{jobs.new_last_7_days:,} new jobs were found in the last 7 days.")
    if jobs.top_companies and jobs.top_companies[0].count > 1:
        c = jobs.top_companies[0]
        out.append(f"{c.name} is hiring the most, with {c.count:,} open roles.")
    if events.closing_within_7_days:
        n = events.closing_within_7_days
        out.append(f"{n} event{'s' if n != 1 else ''} close{'' if n != 1 else 's'} registration in the next 7 days.")
    if events.total_prize_usd >= 1:
        out.append(f"Open events offer about ${events.total_prize_usd:,.0f} in estimated cash prizes.")
    if events.by_type:
        kind, count = max(events.by_type.items(), key=lambda kv: kv[1])
        out.append(f"Most open events are {_label(kind)}s ({count} of {events.total_active}).")
    if businesses.total and businesses.no_website_count:
        out.append(
            f"{businesses.no_website_count:,} of {businesses.total:,} businesses have no website, "
            f"which makes them likely leads for web services."
        )
    return out


@router.get("", response_model=InsightsResponse)
async def get_insights(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightsResponse:
    """Summary of trends across collected jobs, events and businesses, computed from the data with fixed rules."""
    now = datetime.now(timezone.utc)
    jobs = await _job_insights(db, now)
    events = await _event_insights(db, now)
    businesses = await _business_insights(db)
    return InsightsResponse(
        generated_at=now,
        highlights=build_highlights(jobs, events, businesses),
        jobs=jobs,
        events=events,
        businesses=businesses,
        freshness=DataFreshness(
            jobs=await db.scalar(select(func.max(Job.discovered_at))),
            events=await db.scalar(select(func.max(Event.discovered_at))),
            businesses=await db.scalar(select(func.max(Business.discovered_at))),
        ),
    )
