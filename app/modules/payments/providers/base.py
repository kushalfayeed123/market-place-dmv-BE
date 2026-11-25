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


@dataclass(frozen=True)
class PaymentVerificationResult:
    """Verified transaction details returned by a payment provider."""

    status: str
    amount: int
    currency: str


@dataclass(frozen=True)
class SplitLeg:
    """One leg of a multi-merchant split.

    ``subaccount`` is the provider-side subaccount code for a merchant leg;
    the platform leg uses the provider's own account (subaccount omitted).
    ``amount`` is in minor units and must be the leg's net amount.
    """

    subaccount: str | None
    amount: int
    currency: str
    label: str = ""


@dataclass(frozen=True)
class SplitResult:
    """Result of creating a transaction split with the provider."""

    split_code: str
    provider: str


@dataclass(frozen=True)
class BankAccountResolution:
    """Result of resolving/validating a bank account with the provider."""

    account_number: str
    account_name: str  # name as registered at the bank
    bank_code: str
    bank_name: str | None = None


@dataclass(frozen=True)
class BankInfo:
    """A bank the provider can settle to."""

    code: str
    name: str
    country: str = "NG"
    currency: str = "NGN"


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
        split_code: str | None = None,
    ) -> PaymentInitResult:
        """Create a payment session / transaction with the provider.

        ``split_code`` (when the provider supports transaction splits) fans a
        single buyer transaction out to N merchant subaccounts + the platform
        leg at settlement time — this is how multi-merchant orders settle.

        Returns a :class:`PaymentInitResult` with the provider reference and
        (optionally) a URL the buyer is redirected to.
        """
        ...

    @abc.abstractmethod
    async def verify_transaction(self, provider_reference: str) -> bool:
        """Return ``True`` if the transaction was successful on the provider."""
        ...

    async def verify_transaction_details(
        self, provider_reference: str
    ) -> PaymentVerificationResult | None:
        """Return verified transaction details when the provider supports it."""
        return None

    async def create_subaccount(
        self,
        business_name: str,
        bank_code: str | None = None,
        account_number: str | None = None,
        percentage_charge: float = 0.0,
        settlement_schedule: str = "auto",
    ) -> str | None:
        """Register a merchant subaccount; returns the provider subaccount code.

        Optional — providers without subaccounts return ``None`` and the
        platform settles to merchants from its own ledger instead.
        """
        return None

    async def resolve_bank_account(
        self, bank_code: str, account_number: str, currency: str = "NGN"
    ) -> BankAccountResolution | None:
        """Validate a bank account; returns the registered account name.

        Optional — providers without account resolution return ``None``.
        """
        return None

    async def list_banks(self, country: str = "NG", currency: str = "NGN") -> list[BankInfo]:
        """List banks the provider can settle to in a country/currency."""
        return []

    async def create_transfer_recipient(
        self,
        account_number: str,
        bank_code: str,
        account_name: str,
        currency: str = "NGN",
    ) -> str | None:
        """Create a transfer recipient; returns the provider recipient code.

        Payouts are initiated to this code. Optional.
        """
        return None

    async def initiate_transfer(
        self,
        recipient_code: str,
        amount: int,
        currency: str,
        reference: str,
        reason: str = "",
    ) -> str | None:
        """Send ``amount`` (minor units) to a recipient; returns transfer code."""
        return None

    async def create_split(
        self,
        name: str,
        legs: list[SplitLeg],
        currency: str,
    ) -> SplitResult | None:
        """Create a transaction split (subaccounts + platform leg).

        Returns the ``split_code`` to pass to :meth:`initialize_transaction`,
        or ``None`` when the provider does not support splits.
        """
        return None

    async def initiate_refund(
        self, provider_reference: str, amount: int | None = None
    ) -> bool:
        """Refund (fully or partially) a successful transaction. Optional."""
        return False

    async def initiate_payout(
        self, subaccount_code: str, amount: int, currency: str, reference: str
    ) -> str | None:
        """Transfer funds to a merchant subaccount/bank. Optional."""
        return None
