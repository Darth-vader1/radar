import enum
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin


class JobCategory(str, enum.Enum):
    SOFTWARE_ENGINEERING = "SOFTWARE_ENGINEERING"
    FRONTEND = "FRONTEND"
    BACKEND = "BACKEND"
    CLOUD = "CLOUD"
    DEVOPS = "DEVOPS"
    DATA_SCIENCE = "DATA_SCIENCE"
    AI_ML = "AI_ML"
    CYBERSECURITY = "CYBERSECURITY"
    PRODUCT_DESIGN = "PRODUCT_DESIGN"
    PRODUCT_MANAGEMENT = "PRODUCT_MANAGEMENT"
    OTHER_TECH = "OTHER_TECH"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    INTERNSHIP = "INTERNSHIP"
    GRADUATE_TRAINEE = "GRADUATE_TRAINEE"
    CONTRACT = "CONTRACT"
    FREELANCE = "FREELANCE"


class RemoteStatus(str, enum.Enum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNSPECIFIED = "UNSPECIFIED"


class ExperienceLevel(str, enum.Enum):
    INTERN = "INTERN"
    ENTRY = "ENTRY"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF_PRINCIPAL = "STAFF_PRINCIPAL"
    LEAD_MANAGER = "LEAD_MANAGER"
    UNSPECIFIED = "UNSPECIFIED"


class JobStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSING_SOON = "CLOSING_SOON"
    EXPIRED = "EXPIRED"
    FILLED = "FILLED"
    UNVERIFIED = "UNVERIFIED"


class Job(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "jobs"

    title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    company_name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    normalized_company: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    company_website: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False)
    requirements_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    education_requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category: Mapped[str] = mapped_column(String(60), default=JobCategory.OTHER_TECH.value, index=True, nullable=False)
    employment_type: Mapped[str] = mapped_column(String(40), default=EmploymentType.FULL_TIME.value, index=True, nullable=False)
    remote_status: Mapped[str] = mapped_column(String(40), default=RemoteStatus.UNSPECIFIED.value, index=True, nullable=False)
    experience_level: Mapped[str] = mapped_column(String(40), default=ExperienceLevel.UNSPECIFIED.value, index=True, nullable=False)

    salary_min: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    salary_period: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # YEARLY, MONTHLY, HOURLY
    salary_is_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    location_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)

    application_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    application_url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_apply_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)

    primary_source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True
    )
    source_platform: Mapped[str] = mapped_column(String(100), nullable=False)
    original_source_url: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(40), default=JobStatus.ACTIVE.value, index=True, nullable=False)

    # Cross-platform duplicate tracking
    duplicate_cluster_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True, nullable=True)
    other_sources_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    skills: Mapped[List["JobSkill"]] = relationship(
        "JobSkill",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="selectin"
    )


class JobSkill(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_skill: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extraction_origin: Mapped[str] = mapped_column(String(40), default="INFERRED", nullable=False)

    job: Mapped["Job"] = relationship("Job", back_populates="skills")
