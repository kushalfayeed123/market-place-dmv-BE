# app/schemas/store.py
"""
Pydantic schemas for store requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class StoreCreate(BaseModel):
    merchant_id: str
    name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    branding: Optional[Dict[str, Any]] = {}


class StoreResponse(BaseModel):
    id: str
    merchant_id: str
    name: str
    slug: str
    branding: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
