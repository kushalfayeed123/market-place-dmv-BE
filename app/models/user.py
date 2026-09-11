# app/models/user.py
"""
User model representing platform users (buyers, merchants, admins).
"""


from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Index,
    String,
    Text,
    text,
)

from app.db.base import BaseModel
from app.db.types import CITEXT


class UserRole(PyEnum):
    BUYER = "buyer"
    MERCHANT_OWNER = "merchant_owner"
    MERCHANT_STAFF = "merchant_staff"
    PLATFORM_ADMIN = "platform_admin"


class UserStatus(PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Gender(PyEnum):
    """Gender identity options for user profiles."""

    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
    UNSET = "unset"


class User(BaseModel):
    __tablename__ = "users"

    email = Column(CITEXT, unique=True, nullable=False, index=True)
    # VARCHAR(50): unique + indexed column, MySQL cannot index TEXT without a prefix length
    phone = Column(String(50), unique=True, index=True)
    password_hash = Column(Text, nullable=False)
    role = Column(Enum(UserRole), nullable=False, default=UserRole.BUYER)
    email_verified_at = Column(DateTime(timezone=True))
    mfa_secret = Column(Text)  # Encrypted at rest
    mfa_enabled = Column(Boolean, nullable=False, default=False)
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.ACTIVE)

    # Profile fields (nullable for backward compatibility with existing rows)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    avatar_url = Column(Text, nullable=True)
    gender = Column(
        Enum(Gender),
        nullable=True,
        server_default="unset",
    )
    preferred_language = Column(
        String(10),
        nullable=True,
        server_default=text("'en'"),
    )

    # Indexes for performance
    __table_args__ = (
        Index('idx_users_email', email),
        Index('idx_users_phone', phone),
        Index('idx_users_role', role),
        Index('idx_users_status', status),
        Index('idx_users_first_name', first_name),
        Index('idx_users_last_name', last_name),
        Index('idx_users_gender', gender),
        Index('idx_users_preferred_language', preferred_language),
    )

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, role={self.role.value})>"