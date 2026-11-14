"""Response schemas for the rule-based insights summary (no AI involved)."""
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class NamedCount(BaseModel):
    name: str
    count: int


class JobInsights(BaseModel):
    total_active: int
    new_last_7_days: int
    remote_share_pct: float
    with_salary_pct: float
    top_skills: List[NamedCount]
    top_companies: List[NamedCount]
    by_remote_status: Dict[str, int]
    by_experience: Dict[str, int]
    by_category: Dict[str, int]


class UpcomingDeadline(BaseModel):
    id: uuid.UUID
    name: str
    organizer: Optional[str] = None
    deadline: datetime
    prize_summary: Optional[str] = None
    url: str


class EventInsights(BaseModel):
    total_active: int
    closing_within_7_days: int
    total_prize_usd: float
    next_deadlines: List[UpcomingDeadline]
    by_type: Dict[str, int]
    by_delivery_mode: Dict[str, int]


class TopLead(BaseModel):
    id: uuid.UUID
    name: str
    category: Optional[str] = None
    city: Optional[str] = None
    lead_score: int
    has_phone: bool
    website_status: str


class BusinessInsights(BaseModel):
    total: int
    avg_lead_score: float
    no_website_count: int
    top_leads: List[TopLead]
    by_city: Dict[str, int]
    top_categories: List[NamedCount]


class DataFreshness(BaseModel):
    jobs: Optional[datetime] = None
    events: Optional[datetime] = None
    businesses: Optional[datetime] = None


class InsightsResponse(BaseModel):
    generated_at: datetime
    highlights: List[str]
    jobs: JobInsights
    events: EventInsights
    businesses: BusinessInsights
    freshness: DataFreshness
