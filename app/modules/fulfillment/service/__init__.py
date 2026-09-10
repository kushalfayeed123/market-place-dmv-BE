# app/modules/fulfillment/service/__init__.py
"""
Fulfillment service layer.
Provides abstract and concrete implementations for fulfillment operations.
"""

from app.modules.fulfillment.service.base import FulfillmentService
from app.modules.fulfillment.service.dependency import get_fulfillment_service
from app.modules.fulfillment.service.implementation import FulfillmentServiceImpl

__all__ = ["FulfillmentService", "FulfillmentServiceImpl", "get_fulfillment_service"]
