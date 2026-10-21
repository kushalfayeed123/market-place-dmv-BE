# app/models/enums.py
"""
Shared enum definitions for marketplace models.

Centralizes enum classes that are used across multiple model modules
to avoid duplication and keep values consistent.
"""

from enum import Enum as PyEnum


class FulfillmentKindOrder(str, PyEnum):
    SHIPMENT = "shipment"
    DIGITAL_DELIVERY = "digital_delivery"


class FulfillmentStatus(str, PyEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    DELIVERED_DIGITAL = "delivered_digital"
    FAILED = "failed"


class DeliveryMethod(str, PyEnum):
    """Who performs the physical delivery of an order."""
    MERCHANT = "merchant"          # Merchant (or their own staff) delivers
    THIRD_PARTY = "third_party"    # Third-party courier/logistics provider


class InventoryPolicy(str, PyEnum):
    TRACKED = "tracked"
    UNTRACKED = "untracked"
    UNLIMITED = "unlimited"


class DocumentStatus(str, PyEnum):
    """Lifecycle stage of a Document row."""
    PENDING = "pending"      # row created, file not yet uploaded
    COMPLETE = "complete"    # file uploaded and metadata finalized
    CLEANUP = "cleanup"      # soft-delete pending physical removal


class DocumentPurpose(str, PyEnum):
    """Why a document was stored; each maps to a URL column or FK."""
    # Private, merchant-scoped documents
    KYC = "kyc"                       # merchant KYC identity document
    PRODUCT_IMAGE = "product_image"   # product listing image (public via CDN)
    STORE_LOGO = "store_logo"         # store front/logo (public via CDN)
    STORE_BANNER = "store_banner"     # store banner (public via CDN)
    USER_AVATAR = "user_avatar"       # user profile avatar (public via CDN)
