# app/db/base.py
"""
Declarative base for SQLAlchemy models.
Provides common columns and functionality for all models.
"""

import uuid

from app.db.types import UUID
from sqlalchemy import Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base

# Create the declarative base
Base = declarative_base()

class BaseModel(Base):
    """Base model with common fields for all tables."""
    __abstract__ = True
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # CURRENT_TIMESTAMP works on both MySQL (5.6+) and PostgreSQL, whereas
    # now() is only accepted as a DEFAULT by PostgreSQL.
    created_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)