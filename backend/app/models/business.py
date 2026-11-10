import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDMixin


class WebsiteStatus(str, enum.Enum):
    HAS_WEBSITE = "HAS_WEBSITE"
    NO_WEBSITE_FOUND = "NO_WEBSITE_FOUND"
    WEBSITE_UNREACHABLE = "WEBSITE_UNREACHABLE"
    WEBSITE_BROKEN = "WEBSITE_BROKEN"
    WEBSITE_REDIRECTS_INCORRECTLY = "WEBSITE_REDIRECTS_INCORRECTLY"
    WEBSITE_REQUIRES_MANUAL_VERIFICATION = "WEBSITE_REQUIRES_MANUAL_VERIFICATION"
    NOT_CHECKED = "NOT_CHECKED"


class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"
    CATCH_ALL = "CATCH_ALL"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"


class ContactType(str, enum.Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    WHATSAPP = "WHATSAPP"
    CONTACT_FORM = "CONTACT_FORM"


class SocialPlatform(str, enum.Enum):
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    X_TWITTER = "X_TWITTER"
    LINKEDIN = "LINKEDIN"
    TIKTOK = "TIKTOK"
    YOUTUBE = "YOUTUBE"
    OTHER = "OTHER"


class Business(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    category_origin: Mapped[str] = mapped_column(String(40), default="UNVERIFIED", nullable=False)

    phone_number: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    normalized_phone_e164: Mapped[Optional[str]] = mapped_column(String(30), index=True, nullable=True)
    phone_verification_status: Mapped[str] = mapped_column(String(40), default=VerificationStatus.MISSING.value, nullable=False)

    public_email: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    email_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    email_verification_status: Mapped[str] = mapped_column(String(40), default=VerificationStatus.MISSING.value, nullable=False)

    website_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website_domain: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    website_status: Mapped[str] = mapped_column(String(60), default=WebsiteStatus.NOT_CHECKED.value, index=True, nullable=False)

    has_online_ordering: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    online_presence: Mapped[str] = mapped_column(String(40), default="UNKNOWN", nullable=False)

    physical_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(120), index=True, nullable=True)
    country: Mapped[str] = mapped_column(String(120), index=True, nullable=False)

    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    primary_source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="SET NULL"),
        nullable=True
    )
    original_source_url: Mapped[str] = mapped_column(Text, nullable=False)

    lead_score: Mapped[int] = mapped_column(SmallInteger, default=0, index=True, nullable=False)
    lead_score_explanation: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    contacts: Mapped[List["BusinessContact"]] = relationship(
        "BusinessContact",
        back_populates="business",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    social_profiles: Mapped[List["BusinessSocialProfile"]] = relationship(
        "BusinessSocialProfile",
        back_populates="business",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    scores: Mapped[List["LeadScore"]] = relationship(
        "LeadScore",
        back_populates="business",
        cascade="all, delete-orphan",
        order_by="desc(LeadScore.calculated_at)"
    )


class BusinessContact(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "business_contacts"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    contact_type: Mapped[str] = mapped_column(String(40), nullable=False)  # EMAIL, PHONE, WHATSAPP, etc.
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_origin: Mapped[str] = mapped_column(String(40), default="UNVERIFIED", nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), default="UNVERIFIED", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    business: Mapped["Business"] = relationship("Business", back_populates="contacts")


class BusinessSocialProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "business_social_profiles"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)  # INSTAGRAM, FACEBOOK, etc.
    profile_url: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    discovery_source: Mapped[str] = mapped_column(String(120), nullable=False)

    business: Mapped["Business"] = relationship("Business", back_populates="social_profiles")


class EmailVerification(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "email_verifications"

    business_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    email_address: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    syntax_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    mx_records_found: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    mx_hosts: Mapped[Optional[List[str]]] = mapped_column(JSONB, default=list, nullable=True)
    disposable_domain: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    role_based_prefix: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default=VerificationStatus.UNKNOWN.value, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class LeadScoringRule(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lead_scoring_rules"

    rule_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    points: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    conditions_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class LeadScore(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "lead_scores"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    breakdown: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(40), default="1.0", nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    business: Mapped["Business"] = relationship("Business", back_populates="scores")
