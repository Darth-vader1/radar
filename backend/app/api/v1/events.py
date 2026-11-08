import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.auth import User
from app.models.event import Event, EventCategory, EventCategoryLink, EventStatus
from app.schemas.event import (
    EventCategoryRead,
    EventDrawerDetail,
    EventRead,
    EventStatsResponse,
)

router = APIRouter(prefix="/events", tags=["EventRadar"])

INACTIVE_STATUSES = (EventStatus.REGISTRATION_CLOSED.value, EventStatus.COMPLETED.value)
CLOSING_SOON_WINDOW = timedelta(days=7)


@router.get("", response_model=List[EventRead])
async def list_events(
    event_type: Optional[str] = Query(None),
    delivery_mode: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    active_only: bool = Query(False, description="Exclude events whose registration closed or that are completed"),
    has_cash_prizes: Optional[bool] = Query(None),
    student_eligible: Optional[bool] = Query(None),
    is_free: Optional[bool] = Query(None),
    category: Optional[str] = Query(None, description="Category slug"),
    country: Optional[str] = Query(None),
    deadline_before: Optional[datetime] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Search and filter hackathons, competitions, grants and events discovered by EventRadar.
    Ordered by soonest registration deadline first (events without a deadline last).
    """
    stmt = select(Event).order_by(
        Event.registration_deadline.asc().nulls_last(),
        desc(Event.discovered_at),
    )

    if event_type:
        stmt = stmt.where(Event.event_type == event_type.upper())
    if delivery_mode:
        stmt = stmt.where(Event.delivery_mode == delivery_mode.upper())
    if status_filter:
        stmt = stmt.where(Event.status == status_filter.upper())
    if active_only:
        stmt = stmt.where(Event.status.not_in(INACTIVE_STATUSES))
    if has_cash_prizes is not None:
        stmt = stmt.where(Event.has_cash_prizes == has_cash_prizes)
    if student_eligible is not None:
        stmt = stmt.where(Event.student_eligible == student_eligible)
    if is_free is not None:
        stmt = stmt.where(Event.is_free_participation == is_free)
    if country:
        stmt = stmt.where(func.lower(Event.country) == country.lower())
    if deadline_before:
        stmt = stmt.where(Event.registration_deadline <= deadline_before)
    if category:
        stmt = stmt.where(
            Event.id.in_(
                select(EventCategoryLink.event_id)
                .join(EventCategory, EventCategory.id == EventCategoryLink.category_id)
                .where(EventCategory.slug == category.lower())
            )
        )
    if search:
        search_term = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(Event.name).like(search_term)
            | func.lower(func.coalesce(Event.organizer, "")).like(search_term)
            | func.lower(Event.description).like(search_term)
        )

    stmt = stmt.limit(limit).offset(offset)
    results = await db.scalars(stmt)
    return list(results.all())


@router.get("/categories", response_model=List[EventCategoryRead])
async def list_event_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = await db.scalars(select(EventCategory).order_by(EventCategory.name))
    return list(results.all())


@router.get("/stats", response_model=EventStatsResponse)
async def get_event_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate counters for the EventRadar dashboard (active events only)."""
    now = datetime.now(timezone.utc)
    active = Event.status.not_in(INACTIVE_STATUSES)

    total_active = await db.scalar(select(func.count(Event.id)).where(active)) or 0
    open_count = await db.scalar(
        select(func.count(Event.id)).where(Event.status == EventStatus.OPEN_REGISTRATION.value)
    ) or 0
    closing_soon = await db.scalar(
        select(func.count(Event.id)).where(
            active,
            Event.registration_deadline.is_not(None),
            Event.registration_deadline >= now,
            Event.registration_deadline <= now + CLOSING_SOON_WINDOW,
        )
    ) or 0
    total_prize = await db.scalar(
        select(func.coalesce(func.sum(Event.prize_amount_usd_est), 0)).where(active)
    ) or 0
    student_count = await db.scalar(
        select(func.count(Event.id)).where(active, Event.student_eligible.is_(True))
    ) or 0

    category_rows = await db.execute(
        select(EventCategory.slug, func.count(EventCategoryLink.event_id))
        .join(EventCategoryLink, EventCategoryLink.category_id == EventCategory.id)
        .join(Event, Event.id == EventCategoryLink.event_id)
        .where(active)
        .group_by(EventCategory.slug)
    )
    mode_rows = await db.execute(
        select(Event.delivery_mode, func.count(Event.id)).where(active).group_by(Event.delivery_mode)
    )

    return EventStatsResponse(
        total_active_events=total_active,
        open_registration_count=open_count,
        closing_soon_count=closing_soon,
        total_cash_prize_usd=float(total_prize),
        student_eligible_count=student_count,
        by_category={slug: count for slug, count in category_rows.all()},
        by_delivery_mode={mode: count for mode, count in mode_rows.all()},
    )


@router.get("/{event_id}", response_model=EventDrawerDetail)
async def get_event_detail(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return event
