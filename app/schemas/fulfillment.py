# app/schemas/fulfillment.py
"""
Pydantic schemas for fulfillment requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum


class FulfillmentKindOrder(PyEnum):
    SHIPMENT = "shipment"
    DIGITAL_DELIVERY = "digital_delivery"


class FulfillmentStatus(PyEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DELIVERED_DIGITAL = "delivered_digital"
    FAILED = "failed"


class FulfillmentCreate(BaseModel):
    order_id: str
    type: FulfillmentKindOrder
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    download_token: Optional[str] = None
    dispute_window_ends: Optional[datetime] = None  # Would typically be calculated


class FulfillmentResponse(BaseModel):
    id: str
    order_id: str
    merchant_id: str
    type: str
    status: str
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    download_token: Optional[str] = None
    downloads_used: int = 0
    delivered_at: Optional[datetime] = None
    dispute_window_ends: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ShipmentUpdate(BaseModel):
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    status: Optional[FulfillmentStatus] = None


class DigitalDeliveryUpdate(BaseModel):
    downloads_used: Optional[int] = Field(None, ge=0)
    status: Optional[FulfillmentStatus] = None


class FulfillmentStatusUpdate(BaseModel):
    status: FulfillmentStatus