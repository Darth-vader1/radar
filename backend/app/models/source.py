import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin


class ModuleType(str, enum.Enum):
    BUSINESS = "BUSINESS"
    JOB = "JOB"
    EVENT = "EVENT"


class CollectionMethod(str, enum.Enum):
    OFFICIAL_API = "OFFICIAL_API"
    RSS_FEED = "RSS_FEED"
    STRUCTURED_DATA = "STRUCTURED_DATA"
    DIRECTORY_INTEGRATION = "DIRECTORY_INTEGRATION"
    HTML_SCRAPE = "HTML_SCRAPE"
    JS_RENDERED = "JS_RENDERED"


class ConfigStatus(str, enum.Enum):
    READY = "READY"
    AWAITING_CONFIGURATION = "AWAITING_CONFIGURATION"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStage(str, enum.Enum):
    DISCOVER = "DISCOVER"
    FETCH = "FETCH"
    EXTRACT = "EXTRACT"
    NORMALIZE = "NORMALIZE"
    VALIDATE = "VALIDATE"
    DEDUPLICATE = "DEDUPLICATE"
    ENRICH = "ENRICH"
    AI_CLASSIFY = "AI_CLASSIFY"


class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


class Source(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "sources"

    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    module_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # BUSINESS, JOB, EVENT
    source_category: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    collection_method: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(120), nullable=False)

    requires_credentials: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    required_env_vars: Mapped[List[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    config_status: Mapped[str] = mapped_column(String(40), default=ConfigStatus.READY.value, nullable=False)
    adapter_config: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    crawl_budget_pages: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    schedule_cron: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    respect_robots_txt: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_records_collected: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    runs: Mapped[List["SourceRun"]] = relationship("SourceRun", back_populates="source", cascade="all, delete-orphan")
    extracted_records: Mapped[List["ExtractedRecord"]] = relationship("ExtractedRecord", back_populates="source")


class SourceRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "source_runs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    triggered_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    trigger_type: Mapped[str] = mapped_column(String(40), default="MANUAL", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=RunStatus.QUEUED.value, nullable=False, index=True)
    search_params: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_extracted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_deduplicated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped["Source"] = relationship("Source", back_populates="runs")
    tasks: Mapped[List["ScrapingTask"]] = relationship("ScrapingTask", back_populates="source_run", cascade="all, delete-orphan")

    __table_args__ = (
        # At most one QUEUED/RUNNING run per source (migration 006).
        Index(
            "uq_source_runs_one_active_per_source", "source_id", unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )


class ScrapingTask(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scraping_tasks"

    source_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(120), unique=True, nullable=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=TaskStatus.PENDING.value, nullable=False, index=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    progress_pct: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    payload_ref: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, default=dict, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    source_run: Mapped[Optional["SourceRun"]] = relationship("SourceRun", back_populates="tasks")


class DeadLetterTask(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "dead_letter_tasks"

    scraping_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scraping_tasks.id", ondelete="CASCADE"),
        nullable=False
    )
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    error_type: Mapped[str] = mapped_column(String(160), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExtractedRecord(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "extracted_records"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    source_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_runs.id", ondelete="SET NULL"),
        nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # BUSINESS, JOB, EVENT
    canonical_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processing_status: Mapped[str] = mapped_column(String(40), default="EXTRACTED", nullable=False)
    validation_errors: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="extracted_records")

    __table_args__ = (
        # Idempotent ingestion: concurrent runs cannot record the same item twice (migration 006).
        Index(
            "uq_extracted_records_source_external_id", "source_id", "external_id", unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index("uq_extracted_records_source_content_hash", "source_id", "content_hash", unique=True),
    )
