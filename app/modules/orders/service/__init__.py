# app/modules/orders/service/__init__.py
"""
Orders service layer.
Provides abstract and concrete implementations for order operations.
"""

from app.modules.orders.service.base import OrderService
from app.modules.orders.service.dependency import get_order_service
from app.modules.orders.service.implementation import OrderServiceImpl

__all__ = ["OrderService", "OrderServiceImpl", "get_order_service"]
