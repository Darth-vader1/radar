import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin


class EventType(str, enum.Enum):
    HACKATHON = "HACKATHON"
    COMPETITION = "COMPETITION"
    GRANT = "GRANT"
    CONFERENCE = "CONFERENCE"
    WORKSHOP = "WORKSHOP"
    FELLOWSHIP = "FELLOWSHIP"
    OTHER = "OTHER"


class DeliveryMode(str, enum.Enum):
    PHYSICAL = "PHYSICAL"
    VIRTUAL = "VIRTUAL"
    HYBRID = "HYBRID"
    UNSPECIFIED = "UNSPECIFIED"


class EventStatus(str, enum.Enum):
    OPEN_REGISTRATION = "OPEN_REGISTRATION"
    REGISTRATION_CLOSING_SOON = "REGISTRATION_CLOSING_SOON"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    UPCOMING = "UPCOMING"
    ONGOING = "ONGOING"
    COMPLETED = "COMPLETED"


class EventCategoryLinkOrigin(str, enum.Enum):
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"


class Event(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "events"

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    organizer: Mapped[Optional[str]] = mapped_column(String(200), index=True, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    event_type: Mapped[str] = mapped_column(String(40), default=EventType.HACKATHON.value, index=True, nullable=False)
    delivery_mode: Mapped[str] = mapped_column(String(40), default=DeliveryMode.VIRTUAL.value, index=True, nullable=False)

    location_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)

    registration_url: Mapped[str] = mapped_column(Text, nullable=False)
    event_website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    registration_opens_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registration_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    prize_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_cash_prizes: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    prize_amount_usd_est: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)

    is_free_participation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    eligibility_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    participation_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    student_eligible: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    international_eligible: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    status: Mapped[str] = mapped_column(String(40), default=EventStatus.OPEN_REGISTRATION.value, index=True, nullable=False)

    primary_source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True
    )
    source_platform: Mapped[str] = mapped_column(String(100), default="devpost", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    categories: Mapped[List["EventCategory"]] = relationship(
        "EventCategory",
        secondary="event_category_links",
        back_populates="events",
        lazy="selectin"
    )

    __table_args__ = (
        Index("ix_events_status_type_delivery", "status", "event_type", "delivery_mode"),
        Index("ix_events_deadline_status", "registration_deadline", "status"),
        Index("ix_events_norm_name_organizer", "normalized_name", "organizer"),
    )


class EventCategory(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "event_categories"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    events: Mapped[List["Event"]] = relationship(
        "Event",
        secondary="event_category_links",
        back_populates="categories"
    )


class EventCategoryLink(Base):
    __tablename__ = "event_category_links"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_categories.id", ondelete="CASCADE"),
        primary_key=True
    )
    origin: Mapped[str] = mapped_column(String(20), default=EventCategoryLinkOrigin.INFERRED.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
