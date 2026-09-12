# app/models/__init__.py
"""
Import every model module so that all tables are registered on
SQLAlchemy's declarative Base.metadata before Alembic reads it.
"""

from app.models.audit_log import AuditLog  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.commission_plan import CommissionPlan  # noqa: F401
from app.models.digital_asset import DigitalAsset  # noqa: F401
from app.models.fulfillment import Fulfillment  # noqa: F401
from app.models.idempotency_key import IdempotencyKey  # noqa: F401
from app.models.inventory import Inventory  # noqa: F401
from app.models.ledger_entry import LedgerEntry  # noqa: F401
from app.models.knowledge_document import KnowledgeDocument  # noqa: F401
from app.models.support_ticket import SupportTicket, SupportTicketEvent  # noqa: F401
from app.models.merchant import Merchant  # noqa: F401
from app.models.merchant_payout_account import MerchantPayoutAccount  # noqa: F401
from app.models.order import Order  # noqa: F401
from app.models.order_item import OrderItem  # noqa: F401
from app.models.payment_transaction import PaymentTransaction  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.product_attribute_schema import ProductAttributeSchema  # noqa: F401
from app.models.product_variant import ProductVariant  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.store import Store  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.webhook_event import WebhookEvent  # noqa: F401
