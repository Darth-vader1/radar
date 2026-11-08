import uuid
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class RefreshRequest(BaseModel):
    # Optional: browser clients send the refresh token as an httpOnly cookie instead.
    refresh_token: Optional[str] = None


class TokenPayload(BaseModel):
    sub: str
    type: str
    exp: int


class UserLogin(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=128, description="Minimum 8 characters")
    full_name: Optional[str] = Field(None, max_length=160)


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_verified: bool
    roles: List[RoleRead] = []
    created_at: datetime


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    scopes: List[str] = Field(default_factory=lambda: ["read"])
    rate_limit_per_minute: int = Field(default=60, ge=1, le=1000)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: List[str]
    rate_limit_per_minute: int
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class ApiKeyCreatedResponse(ApiKeyRead):
    raw_api_key: str = Field(..., description="Copy this key now; it cannot be shown again.")
