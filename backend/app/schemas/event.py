import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class EventCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: Optional[str] = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    normalized_name: str
    organizer: Optional[str] = None
    event_type: str
    delivery_mode: str
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    registration_url: str
    event_website: Optional[str] = None
    registration_opens_at: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    prize_summary: Optional[str] = None
    has_cash_prizes: bool
    prize_amount_usd_est: Optional[float] = None
    is_free_participation: bool
    student_eligible: Optional[bool] = None
    international_eligible: Optional[bool] = None
    status: str
    source_platform: str
    source_url: str
    discovered_at: datetime
    last_verified_at: Optional[datetime] = None
    categories: List[EventCategoryRead] = []


class EventDrawerDetail(EventRead):
    description: str
    eligibility_text: Optional[str] = None
    participation_requirements: Optional[str] = None


class EventCreate(BaseModel):
    name: str
    organizer: Optional[str] = None
    description: str
    event_type: str = "HACKATHON"
    delivery_mode: str = "VIRTUAL"
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    registration_url: str
    event_website: Optional[str] = None
    registration_opens_at: Optional[datetime] = None
    registration_deadline: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    prize_summary: Optional[str] = None
    has_cash_prizes: bool = False
    prize_amount_usd_est: Optional[float] = None
    is_free_participation: bool = True
    eligibility_text: Optional[str] = None
    participation_requirements: Optional[str] = None
    student_eligible: Optional[bool] = None
    international_eligible: Optional[bool] = None
    source_platform: str = "devpost"
    source_url: str
    categories: List[str] = []


class EventFilterParams(BaseModel):
    event_type: Optional[str] = None
    delivery_mode: Optional[str] = None
    status: Optional[str] = None
    has_cash_prizes: Optional[bool] = None
    student_eligible: Optional[bool] = None
    is_free: Optional[bool] = None
    category: Optional[str] = None
    country: Optional[str] = None
    search: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class EventStatsResponse(BaseModel):
    total_active_events: int
    open_registration_count: int
    closing_soon_count: int
    total_cash_prize_usd: float
    student_eligible_count: int
    by_category: dict[str, int]
    by_delivery_mode: dict[str, int]
