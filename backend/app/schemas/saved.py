import re
import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EntityType = Literal["BUSINESS", "JOB", "EVENT"]

MAX_TAGS = 10
MAX_TAG_LENGTH = 32
MAX_NOTE_LENGTH = 2000


def clean_tags(tags: Optional[List[str]]) -> List[str]:
    """Lower-case, trim, collapse spaces, de-duplicate (keeping order), cap count and length."""
    seen: list[str] = []
    for raw in tags or []:
        tag = re.sub(r"\s+", " ", str(raw)).strip().lower()[:MAX_TAG_LENGTH]
        if tag and tag not in seen:
            seen.append(tag)
    if len(seen) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags per saved record.")
    return seen


class _Editable(BaseModel):
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)
    tags: Optional[List[str]] = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        return None if v is None else clean_tags(v)

    @field_validator("note")
    @classmethod
    def _note(cls, v: Optional[str]) -> Optional[str]:
        return (v.strip() or None) if v is not None else None


class SavedRecordCreate(_Editable):
    entity_type: EntityType
    entity_id: uuid.UUID


class SavedRecordUpdate(_Editable):
    pass


class EntitySummary(BaseModel):
    title: str
    subtitle: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    facts: dict[str, Any] = {}


class SavedRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: EntityType
    entity_id: uuid.UUID
    note: Optional[str] = None
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime
    # None when the business/job/event has since been removed from RADAR.
    entity: Optional[EntitySummary] = None
