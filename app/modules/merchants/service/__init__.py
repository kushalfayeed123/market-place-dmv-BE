# app/modules/merchants/service/__init__.py
"""
Merchant service layer.
Provides abstract and concrete implementations for merchant operations.
"""

from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.modules.merchants.service.implementation import MerchantServiceImpl

__all__ = ["MerchantService", "MerchantServiceImpl", "get_merchant_service"]
