# app/models/enums.py
"""
Shared enum definitions for marketplace models.

Centralizes enum classes that are used across multiple model modules
to avoid duplication and keep values consistent.
"""

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


class InventoryPolicy(PyEnum):
    TRACKED = "tracked"
    UNTRACKED = "untracked"
    UNLIMITED = "unlimited"
