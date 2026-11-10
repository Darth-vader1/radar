import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class JobSkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    skill_name: str
    normalized_skill: str
    is_required: bool
    extraction_origin: str


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    company_name: str
    company_website: Optional[str] = None
    category: str
    employment_type: str
    remote_status: str
    experience_level: str
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    location_text: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    application_deadline: Optional[datetime] = None
    application_url: str
    source_platform: str
    status: str
    published_at: Optional[datetime] = None
    discovered_at: datetime
    skills: List[JobSkillRead] = []
    other_sources_count: int = 0


class JobDrawerDetail(JobRead):
    description: str
    requirements_text: Optional[str] = None
    education_requirements: Optional[str] = None
    original_source_url: str


class JobFilterParams(BaseModel):
    category: Optional[str] = None
    employment_type: Optional[str] = None
    remote_status: Optional[str] = None
    experience_level: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    skill: Optional[str] = None
    search: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class SkillCountItem(BaseModel):
    skill_name: str
    count: int
