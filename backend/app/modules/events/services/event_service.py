import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database.locks import advisory_xact_lock

from app.models.event import (
    DeliveryMode,
    Event,
    EventCategory,
    EventCategoryLink,
    EventCategoryLinkOrigin,
    EventStatus,
    EventType,
)
from app.modules.events.services.event_classifier import (
    classify_event_categories,
    compute_event_status,
    normalize_event_name,
    parse_prize_amount,
)
from app.schemas.event import EventCreate

logger = logging.getLogger("radar.events.service")


class EventIngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_category(self, slug: str, name: Optional[str] = None) -> EventCategory:
        stmt = select(EventCategory).where(EventCategory.slug == slug)
        cat = await self.db.scalar(stmt)
        if not cat:
            cat = EventCategory(
                slug=slug,
                name=name or slug.replace("-", " ").title(),
                description=f"Auto-created category for {slug}"
            )
            self.db.add(cat)
            await self.db.flush()
        return cat

    async def ingest_event(self, event_data: EventCreate, source_id: Optional[uuid.UUID] = None) -> Tuple[Event, bool]:
        """
        Ingests and deduplicates an event.
        Returns (event_instance, is_created).
        """
        norm_name = normalize_event_name(event_data.name)
        now = datetime.now(timezone.utc)

        # 1. Compute dynamic lifecycle status
        status = compute_event_status(
            start_date=event_data.start_date,
            end_date=event_data.end_date,
            registration_deadline=event_data.registration_deadline,
            registration_opens_at=event_data.registration_opens_at,
            now=now,
        )

        # 2. Parse prizes if not already explicitly provided
        has_cash = event_data.has_cash_prizes
        prize_usd = event_data.prize_amount_usd_est
        prize_summary = event_data.prize_summary

        if not has_cash or prize_usd is None:
            detected_cash, parsed_usd, detected_summary = parse_prize_amount(
                f"{event_data.prize_summary or ''} {event_data.description}"
            )
            if detected_cash:
                has_cash = True
                prize_usd = prize_usd or parsed_usd
                prize_summary = prize_summary or detected_summary

        # Serialize concurrent ingestion of the same event; dedup matches on either key.
        await advisory_xact_lock(
            self.db,
            f"event-url:{event_data.registration_url}",
            f"event-name:{norm_name}:{event_data.organizer or ''}",
        )

        # 3. Check for existing event (Deduplication)
        # Check by registration_url or (normalized_name + organizer)
        reg_domain = urlparse(event_data.registration_url).netloc.lower()
        stmt = select(Event).options(selectinload(Event.categories)).where(
            or_(
                Event.registration_url == event_data.registration_url,
                (Event.normalized_name == norm_name) & (Event.organizer == event_data.organizer)
            )
        )
        existing = await self.db.scalar(stmt)

        if existing:
            # Update mutable fields (deadline, status, prizes)
            existing.status = status
            existing.registration_deadline = event_data.registration_deadline or existing.registration_deadline
            existing.start_date = event_data.start_date or existing.start_date
            existing.end_date = event_data.end_date or existing.end_date
            existing.prize_summary = prize_summary or existing.prize_summary
            existing.has_cash_prizes = has_cash or existing.has_cash_prizes
            existing.prize_amount_usd_est = prize_usd or existing.prize_amount_usd_est
            existing.last_verified_at = now
            await self.db.commit()
            return existing, False

        # 4. Create new Event
        new_event = Event(
            name=event_data.name.strip(),
            normalized_name=norm_name,
            organizer=event_data.organizer.strip() if event_data.organizer else None,
            description=event_data.description,
            event_type=event_data.event_type,
            delivery_mode=event_data.delivery_mode,
            location_text=event_data.location_text,
            city=event_data.city,
            country=event_data.country,
            registration_url=event_data.registration_url,
            event_website=event_data.event_website,
            registration_opens_at=event_data.registration_opens_at,
            registration_deadline=event_data.registration_deadline,
            start_date=event_data.start_date,
            end_date=event_data.end_date,
            prize_summary=prize_summary,
            has_cash_prizes=has_cash,
            prize_amount_usd_est=prize_usd,
            is_free_participation=event_data.is_free_participation,
            eligibility_text=event_data.eligibility_text,
            participation_requirements=event_data.participation_requirements,
            student_eligible=event_data.student_eligible,
            international_eligible=event_data.international_eligible,
            status=status,
            primary_source_id=source_id,
            source_platform=event_data.source_platform,
            source_url=event_data.source_url,
            discovered_at=now,
            last_verified_at=now,
        )
        self.db.add(new_event)
        await self.db.flush()

        # 5. Extract and link categories
        category_slugs = classify_event_categories(
            name=event_data.name,
            description=event_data.description,
            tags=event_data.categories
        )

        for cat_slug in category_slugs:
            category_obj = await self.get_or_create_category(cat_slug)
            link = EventCategoryLink(
                event_id=new_event.id,
                category_id=category_obj.id,
                origin=EventCategoryLinkOrigin.INFERRED.value
            )
            self.db.add(link)

        await self.db.commit()

        # Re-fetch with categories loaded
        stmt_refresh = select(Event).options(selectinload(Event.categories)).where(Event.id == new_event.id)
        saved = await self.db.scalar(stmt_refresh)
        return saved, True
