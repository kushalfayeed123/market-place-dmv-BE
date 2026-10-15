# app/modules/payments/providers/registry.py
"""Registry of payment providers.

Maps provider names (paystack, flutterwave, stripe) to their implementations.
Providers that are declared but not yet implemented are listed with
``implemented=False`` so callers can gracefully report them as "disabled".
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.payments.providers.base import PaymentProvider
from app.modules.payments.providers.paystack import PaystackProvider


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata about a payment provider."""

    key: str
    name: str
    implemented: bool
    supported_currencies: list[str]


# ── Registry ────────────────────────────────────────────────────────────────

# Paystack is the Phase-1 provider and is fully implemented.
# Flutterwave and Stripe are declared but NOT implemented — they show as
# disabled in the UI so merchants/buyers know they'll be available later.
_PROVIDER_REGISTRY: dict[str, type[PaymentProvider]] = {
    "paystack": PaystackProvider,
}

_PROVIDER_INFO: dict[str, ProviderInfo] = {
    "paystack": ProviderInfo(
        key="paystack",
        name="Paystack",
        implemented=True,
        supported_currencies=["NGN", "GHS", "KES", "ZAR", "USD"],
    ),
    "flutterwave": ProviderInfo(
        key="flutterwave",
        name="Flutterwave",
        implemented=False,
        supported_currencies=["NGN", "USD", "EUR", "GBP"],
    ),
    "stripe": ProviderInfo(
        key="stripe",
        name="Stripe",
        implemented=False,
        supported_currencies=["USD", "EUR", "GBP"],
    ),
}


def get_provider(provider_name: str) -> PaymentProvider | None:
    """Return a provider instance by key, or ``None`` if not registered."""
    cls = _PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        return None
    return cls()


def get_available_providers(currency: str | None = None) -> list[ProviderInfo]:
    """Return all registered providers, optionally filtered by currency.

    Includes unimplemented providers so the frontend can show them as disabled.
    """
    providers = list(_PROVIDER_INFO.values())
    if currency:
        providers = [
            p for p in providers if currency in p.supported_currencies
        ]
    return providers


def is_provider_implemented(provider_name: str) -> bool:
    """Return True if the provider is both registered and implemented."""
    info = _PROVIDER_INFO.get(provider_name)
    if info is None:
        return False
    return info.implemented


class PaymentProviderRegistry:
    """Facade over the registry for dependency injection."""

    @staticmethod
    def get_provider(provider_name: str) -> PaymentProvider | None:
        return get_provider(provider_name)

    @staticmethod
    def get_available_providers(
        currency: str | None = None,
    ) -> list[ProviderInfo]:
        return get_available_providers(currency)

    @staticmethod
    def is_provider_implemented(provider_name: str) -> bool:
        return is_provider_implemented(provider_name)