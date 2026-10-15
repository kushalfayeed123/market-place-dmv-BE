# app/modules/payments/providers/base.py
"""Abstract PaymentProvider interface.

The rest of the system depends on this abstraction so payment gateways can be
swapped or extended without touching order / ledger / webhook code.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


# ── Value objects ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PaymentInitResult:
    """Result of initialising a payment with a provider.

    ``provider_reference`` is the transaction/reference id the provider
    assigned (e.g. Paystack's ``reference``).  ``payment_url`` is the URL the
    buyer must visit to authorise / complete the payment.
    """

    provider_reference: str
    payment_url: str | None = None
    status: str = "initialized"


# ── Enum-like constants (kept as plain strings for DB / JSON compat) ─────────

class PaymentStatus:
    """Canonical status strings used across providers."""
    INITIALIZED = "initialized"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


# ── Interface ─────────────────────────────────────────────────────────────────

class PaymentProvider(abc.ABC):
    """Abstract interface all payment provider implementations must satisfy."""

    #: Human-readable name, e.g. "Paystack"
    name: str

    #: Provider key used in the DB / API, e.g. "paystack"
    provider_key: str

    #: Whether this provider is actually wired up to a real gateway.
    #: Providers that are declared but not yet integrated must set this ``False``.
    implemented: bool = True

    @abc.abstractmethod
    async def initialize_transaction(
        self,
        order_id: str,
        amount: int,          # minor units
        currency: str,        # ISO 4217
        buyer_email: str | None = None,
        callback_url: str | None = None,
        metadata: dict | None = None,
    ) -> PaymentInitResult:
        """Create a payment session / transaction with the provider.

        Returns a :class:`PaymentInitResult` with the provider reference and
        (optionally) a URL the buyer is redirected to.
        """
        ...

    @abc.abstractmethod
    async def verify_transaction(self, provider_reference: str) -> bool:
        """Return ``True`` if the transaction was successful on the provider."""
        ...
