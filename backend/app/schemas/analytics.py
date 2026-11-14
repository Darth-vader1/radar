"""Response schemas for the analytics page: trends over time, crawler health and geography."""
import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

from app.schemas.insights import NamedCount


class DailyDiscoveries(BaseModel):
    date: date
    jobs: int = 0
    events: int = 0
    businesses: int = 0


class SourceDiscoveries(BaseModel):
    source: str
    entity_type: str
    count: int


class DailyRuns(BaseModel):
    date: date
    completed: int = 0
    partial: int = 0
    failed: int = 0


class SourceHealth(BaseModel):
    id: uuid.UUID
    name: str
    module_type: str
    is_enabled: bool
    runs: int
    completed: int
    partial: int
    failed: int
    success_rate_pct: Optional[float] = None  # None when the source had no finished runs in the window
    avg_duration_seconds: Optional[float] = None
    avg_records_created: Optional[float] = None
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_error_message: Optional[str] = None
    open_failed_tasks: int
    total_records_collected: int


class Geography(BaseModel):
    jobs_by_country: List[NamedCount]
    jobs_remote: int
    jobs_total: int
    nigeria_jobs: int
    businesses_by_city: List[NamedCount]
    events_by_mode: List[NamedCount]


class WeeklyPrizes(BaseModel):
    week_start: date
    prize_usd: float
    events: int


class AnalyticsResponse(BaseModel):
    generated_at: datetime
    days: int
    discoveries: List[DailyDiscoveries]
    discoveries_by_source: List[SourceDiscoveries]
    runs: List[DailyRuns]
    source_health: List[SourceHealth]
    geography: Geography
    prizes_by_deadline_week: List[WeeklyPrizes]
