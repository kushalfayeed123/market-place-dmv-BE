# app/models/merchant.py
"""
Merchant model representing business entities on the platform.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    CHAR,
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from app.db.types import UUID, ENUM as PgEnum
from sqlalchemy.sql import func

from app.db.base import BaseModel

class KycStatus(PyEnum):
    PENDING = "pending"
    TEST_MODE = "test_mode"
    VERIFIED = "verified"
    REJECTED = "rejected"

class Merchant(BaseModel):
    __tablename__ = "merchants"

    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    business_name = Column(Text, nullable=False)
    # VARCHAR(255): unique + indexed column, MySQL cannot index TEXT without a prefix length
    slug = Column(String(255), nullable=False, unique=True)
    kyc_status = Column(PgEnum(KycStatus), nullable=False, default=KycStatus.PENDING)
    kyc_provider_ref = Column(Text)  # Reference ID from identity API
    commission_plan_id = Column(UUID(as_uuid=True), ForeignKey("commission_plans.id"), nullable=False)

    # Merchant address fields (nullable for backward compatibility)
    address_line1 = Column(Text, nullable=True)
    address_line2 = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    country = Column(CHAR(2), nullable=True)  # ISO 3166-1 alpha-2

    # Indexes and constraints
    __table_args__ = (
        Index('idx_merchants_owner', owner_user_id),
        Index('idx_merchants_slug', slug),
        Index('idx_merchants_kyc_status', kyc_status),
        Index('idx_merchants_country', country),
        UniqueConstraint('slug', name='uq_merchants_slug'),
    )

    def __repr__(self):
        return f"<Merchant(id={self.id}, business_name={self.business_name}, kyc_status={self.kyc_status.value})>"