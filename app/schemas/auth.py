# app/schemas/auth.py
"""
Pydantic schemas for authentication requests and responses.
"""

from datetime import date, datetime
from enum import Enum as PyEnum

from pydantic import BaseModel, EmailStr, Field


class UserRole(str, PyEnum):
    """Mirrors app.models.user.UserRole for schema-level validation."""

    BUYER = "buyer"
    MERCHANT_OWNER = "merchant_owner"
    MERCHANT_STAFF = "merchant_staff"
    PLATFORM_ADMIN = "platform_admin"


class UserStatus(str, PyEnum):
    """Mirrors app.models.user.UserStatus for schema-level validation."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Gender(str, PyEnum):
    """Mirrors app.models.user.Gender for schema-level validation."""

    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    UNSET = "unset"


class UserRegister(BaseModel):
    email: EmailStr
    phone: str | None = None
    password: str = Field(..., min_length=8)
    role: str = Field(default="buyer", pattern="^(buyer|merchant_owner)$")

    # Profile fields
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: date | None = None
    preferred_language: str = Field(default="en", max_length=10)
    gender: Gender | None = Gender.UNSET
    avatar_url: str | None = None


class UserUpdate(BaseModel):
    """Partial-update schema for the PUT /auth/me endpoint.

    Every field is optional so that callers can patch individual attributes
    without resending the full profile.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = None
    date_of_birth: date | None = None
    avatar_url: str | None = None
    preferred_language: str | None = Field(default=None, max_length=10)
    gender: Gender | None = None


class PasswordChange(BaseModel):
    """Schema for the PUT /auth/me/password endpoint."""

    current_password: str
    new_password: str = Field(..., min_length=8)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Full user profile returned by GET /me and after PUT /me."""

    id: str
    email: str
    phone: str | None = None
    role: str
    status: str
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    avatar_url: str | None = None
    preferred_language: str | None = None
    gender: str | None = None
    email_verified_at: datetime | None = None
    mfa_enabled: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class MFASetup(BaseModel):
    secret: str | None = None  # If not provided, one will be generated


class MFAVerify(BaseModel):
    token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)