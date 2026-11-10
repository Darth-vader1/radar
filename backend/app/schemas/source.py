import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator


class _CronValidated(BaseModel):
    @field_validator("schedule_cron", check_fields=False)
    @classmethod
    def _valid_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not croniter.is_valid(v):
            raise ValueError(f"'{v}' is not a valid 5-field cron expression (e.g. '0 */6 * * *').")
        return v


class SourceBase(BaseModel):
    slug: str = Field(..., max_length=100)
    name: str = Field(..., max_length=160)
    module_type: str = Field(..., description="BUSINESS | JOB | EVENT")
    source_category: str = Field(..., max_length=80)
    base_url: str
    collection_method: str = Field(..., description="OFFICIAL_API | RSS_FEED | STRUCTURED_DATA | DIRECTORY_INTEGRATION | HTML_SCRAPE | JS_RENDERED")
    adapter_key: str = Field(..., max_length=120)
    requires_credentials: bool = False
    required_env_vars: List[str] = Field(default_factory=list)
    adapter_config: Dict[str, Any] = Field(default_factory=dict)
    rate_limit_rpm: int = Field(default=30, ge=1, le=600)
    max_concurrency: int = Field(default=2, ge=1, le=10)
    crawl_budget_pages: int = Field(default=100, ge=1, le=10000)
    schedule_cron: Optional[str] = None
    is_enabled: bool = True
    respect_robots_txt: bool = True


class SourceCreate(SourceBase, _CronValidated):
    pass


class SourceUpdate(_CronValidated):
    name: Optional[str] = None
    source_category: Optional[str] = None
    base_url: Optional[str] = None
    adapter_config: Optional[Dict[str, Any]] = None
    rate_limit_rpm: Optional[int] = None
    max_concurrency: Optional[int] = None
    crawl_budget_pages: Optional[int] = None
    schedule_cron: Optional[str] = None
    is_enabled: Optional[bool] = None
    respect_robots_txt: Optional[bool] = None


class SourceRead(SourceBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    config_status: str
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error_message: Optional[str] = None
    total_records_collected: int = 0
    created_at: datetime
    updated_at: datetime


class SourceRunCreate(BaseModel):
    source_id: uuid.UUID
    trigger_type: str = "MANUAL"
    search_params: Dict[str, Any] = Field(default_factory=dict)


class SourceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    trigger_type: str
    status: str
    search_params: Dict[str, Any]
    pages_fetched: int
    records_extracted: int
    records_created: int
    records_updated: int
    records_deduplicated: int
    errors_count: int
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_summary: Optional[str] = None
    created_at: datetime


class ScrapingTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_run_id: Optional[uuid.UUID]
    source_id: Optional[uuid.UUID]
    celery_task_id: Optional[str]
    stage: str
    status: str
    retry_count: int
    max_retries: int
    progress_pct: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class SourceConfigCheckResult(BaseModel):
    source_id: uuid.UUID
    slug: str
    is_configured: bool
    status: str
    missing_env_vars: List[str]
    message: str
