import enum
import uuid
from typing import List, Optional

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDMixin


class SavedEntityType(str, enum.Enum):
    BUSINESS = "BUSINESS"
    JOB = "JOB"
    EVENT = "EVENT"


class SavedRecord(Base, UUIDMixin, TimestampMixin):
    """A user's bookmark of a business, job or event, with their own note and tags."""

    __tablename__ = "saved_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Not a foreign key: it points at one of three tables. Rows whose entity was deleted are
    # reported as unavailable by the API rather than silently disappearing.
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[List[str]] = mapped_column(ARRAY(String(32)), default=list, server_default="{}", nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "entity_type", "entity_id", name="uq_saved_records_user_entity"),
        Index("ix_saved_records_user_created", "user_id", "created_at"),
        Index("ix_saved_records_tags", "tags", postgresql_using="gin"),
    )
