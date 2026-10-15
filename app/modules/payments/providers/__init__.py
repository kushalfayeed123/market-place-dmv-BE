# app/modules/payments/providers/__init__.py
"""Payment provider abstraction.

Defines a pluggable ``PaymentProvider`` interface so that the rest of the
system (the payment service, the checkout flow) stays decoupled from any
specific payment gateway.  ``PaystackProvider`` is the Phase-1 implementation;
Flutterwave and Stripe are declared but **not implemented** — they are listed
in the registry with ``implemented=False`` so the frontend can grey them out.
"""

from app.modules.payments.providers.base import (
    PaymentProvider,
    PaymentInitResult,
    PaymentStatus,
)
from app.modules.payments.providers.paystack import PaystackProvider
from app.modules.payments.providers.registry import (
    PaymentProviderRegistry,
    get_provider,
    get_available_providers,
    is_provider_implemented,
)

__all__ = [
    "PaymentProvider",
    "PaymentInitResult",
    "PaymentStatus",
    "PaystackProvider",
    "PaymentProviderRegistry",
    "get_provider",
    "get_available_providers",
    "is_provider_implemented",
]