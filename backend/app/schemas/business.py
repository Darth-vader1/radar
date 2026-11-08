import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class BusinessContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_type: str
    value: str
    normalized_value: str
    discovery_source: str
    verification_status: str
    confidence_score: float
    is_primary: bool


class BusinessSocialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: str
    profile_url: str
    handle: Optional[str] = None
    is_active: Optional[bool] = None


class LeadScoreBreakdownItem(BaseModel):
    rule_key: str
    label: str
    points: int
    matched: bool
    explanation: str


class BusinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    phone_number: Optional[str] = None
    phone_verification_status: str
    public_email: Optional[str] = None
    email_verification_status: str
    website_url: Optional[str] = None
    website_status: str
    has_online_ordering: Optional[bool] = None
    online_presence: str
    physical_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    original_source_url: str
    lead_score: int
    lead_score_explanation: List[Dict[str, Any]] = []
    discovered_at: datetime
    last_verified_at: Optional[datetime] = None


class BusinessDrawerDetail(BusinessRead):
    contacts: List[BusinessContactRead] = []
    social_profiles: List[BusinessSocialRead] = []


class BusinessFilterParams(BaseModel):
    country: Optional[str] = "Nigeria"
    state: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    website_status: Optional[str] = None
    min_lead_score: Optional[int] = Field(None, ge=0, le=100)
    has_email: Optional[bool] = None
    has_phone: Optional[bool] = None
    query: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)


class LeadScoringRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_key: str
    label: str
    points: int
    is_enabled: bool
    conditions_json: Dict[str, Any]


class LeadRuleUpdate(BaseModel):
    points: Optional[int] = Field(None, ge=-50, le=50)
    is_enabled: Optional[bool] = None
    label: Optional[str] = None
