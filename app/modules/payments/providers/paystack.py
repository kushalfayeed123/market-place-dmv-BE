# app/modules/payments/providers/paystack.py
"""Paystack payment provider implementation.

Calls the Paystack Initialise Transaction API when a real secret key is
configured.  When no real key is present (dev / test environments that use
placeholder values), it falls back to a deterministic local stub so the
end-to-end flow is still exercisable without hitting the network.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings
from app.modules.payments.providers.base import (
    BankAccountResolution,
    BankInfo,
    PaymentInitResult,
    PaymentProvider,
    PaymentVerificationResult,
    SplitLeg,
    SplitResult,
)

# Paystack API base URL — production uses api.paystack.co, but test keys
# also work against that endpoint.
PAYSTACK_API_BASE = "https://api.paystack.co"


class PaystackProvider(PaymentProvider):
    """Paystack implementation of :class:`PaymentProvider`."""

    name = "Paystack"
    provider_key = "paystack"
    implemented = True

    # ── Internal helpers ──────────────────────────────────────────────

    @property
    def _configured(self) -> bool:
        """True when a real (non-placeholder) secret key is set."""
        key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
        if not key or key == "sk_test_your_test_key_here":
            return False
        return key.startswith("sk_")

    @property
    def _public_key(self) -> str:
        return getattr(settings, "PAYSTACK_PUBLIC_KEY", "")

    def _is_placeholder(self, key: str) -> bool:
        return not key or key == "sk_test_your_test_key_here"

    # ── Public API ───────────────────────────────────────────────────

    async def initialize_transaction(
        self,
        order_id: str,
        amount: int,
        currency: str,
        buyer_email: str | None = None,
        callback_url: str | None = None,
        metadata: dict | None = None,
        split_code: str | None = None,
        subaccount: str | None = None,
        transaction_charge: int | None = None,
    ) -> PaymentInitResult:
        """Initialise a Paystack transaction.

        When credentials are not configured (dev / test), falls back to a
        local stub that generates a reference and a mock authorization URL.
        ``split_code`` attaches a pre-created Transaction Split. ``subaccount``
        and ``transaction_charge`` route a single-merchant payment directly to
        its subaccount while retaining the platform commission.
        """
        # Paystack's initialize endpoint REQUIRES a real customer email —
        # never fall back to a placeholder address on the live path.
        if not buyer_email:
            raise ValueError("buyer_email is required to initialize a Paystack transaction")
        if not self._configured:
            return self._stub_initialize(order_id, amount, currency, metadata, buyer_email=buyer_email)

        # Build the request body for Paystack's initialize endpoint.
        # The callback_url must be the storefront frontend — Paystack appends
        # ?trxref=...&reference=... to it after payment, and the frontend uses
        # those params to reload the checkout state and verify the payment.
        frontend_base = (settings.PUBLIC_BASE_URL or settings.FRONTEND_URL or "").rstrip("/")
        body: dict = {
            "email": buyer_email,
            "amount": amount,
            "currency": currency,
            "reference": f"ord_{order_id}_{uuid.uuid4().hex[:12]}",
            "callback_url": (callback_url or frontend_base or None),
        }
        if split_code:
            body["split_code"] = split_code
        if subaccount:
            body["subaccount"] = subaccount
        if transaction_charge is not None:
            if transaction_charge < 0:
                raise ValueError("transaction_charge cannot be negative")
            body["transaction_charge"] = transaction_charge
        if metadata:
            body["metadata"] = metadata

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        url = f"{PAYSTACK_API_BASE}/transaction/initialize"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=body, headers=headers)
                data = resp.json()

            if resp.status_code != 200 or not data.get("status", True):
                # Paystack returns status=False on error; surface the provider
                # message instead of silently stubbing with a fake email.
                raise RuntimeError(
                    f"Paystack initialize failed: {data.get('message', 'unknown error')}"
                )

            data = data.get("data", {})
            return PaymentInitResult(
                provider_reference=data.get("reference", body["reference"]),
                payment_url=data.get("authorization_url"),
                status="initialized",
            )
        except RuntimeError:
            raise
        except Exception as exc:
            # On any network / API error, surface it — do not mask provider
            # failures with a stub that hides the real buyer email.
            raise RuntimeError(f"Paystack initialize request failed: {exc}") from exc

    async def verify_transaction(self, provider_reference: str) -> bool:
        """Verify a Paystack transaction by reference."""
        if not self._configured:
            return False

        url = f"{PAYSTACK_API_BASE}/transaction/verify/{provider_reference}"
        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()

            if resp.status_code != 200 or not data.get("status", True):
                return False

            return data.get("data", {}).get("status") == "success"
        except Exception:
            return False

    async def verify_transaction_details(
        self, provider_reference: str
    ) -> PaymentVerificationResult | None:
        """Fetch Paystack's verified status, amount, and currency."""
        if not self._configured:
            return None

        url = f"{PAYSTACK_API_BASE}/transaction/verify/{provider_reference}"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers)
                response_data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("Could not verify the payment with Paystack.") from exc

        if response.status_code != 200 or not response_data.get("status", True):
            return None

        transaction = response_data.get("data", {})
        amount = transaction.get("amount")
        currency = transaction.get("currency")
        if not isinstance(amount, int) or not isinstance(currency, str):
            return None
        return PaymentVerificationResult(
            status=str(transaction.get("status", "unknown")),
            amount=amount,
            currency=currency,
        )

    # ── Subaccounts & transaction splits (multi-vendor settlement) ────────

    async def create_subaccount(
        self,
        business_name: str,
        bank_code: str | None = None,
        account_number: str | None = None,
        percentage_charge: float = 0.0,
        settlement_schedule: str = "auto",
    ) -> str | None:
        """Create a Paystack subaccount for a merchant.

        Falls back to a deterministic stub code when credentials are not
        configured so the dev/test flow still exercises the split path.
        """
        if not self._configured:
            return f"ACCT_stub_{uuid.uuid4().hex[:16]}"

        body: dict = {
            "business_name": business_name,
            "percentage_charge": percentage_charge,
            "settlement_schedule": settlement_schedule,
        }
        if bank_code and account_number:
            body["settlement_bank"] = bank_code
            body["account_number"] = account_number

        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{PAYSTACK_API_BASE}/subaccount", json=body, headers=headers
                )
                data = resp.json()
            if resp.status_code not in (200, 201) or not data.get("status", False):
                raise RuntimeError(
                    f"Paystack subaccount creation failed: {data.get('message', 'unknown error')}"
                )
            return data.get("data", {}).get("subaccount_code")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Paystack subaccount creation failed: {exc}") from exc

    # ── Bank account validation & payouts ──────────────────────────────────

    async def resolve_bank_account(
        self, bank_code: str, account_number: str, currency: str = "NGN"
    ) -> BankAccountResolution | None:
        """Validate a bank account via Paystack's bank-resolve endpoint.

        Returns the registered account name, or raises ``ValueError`` when the
        account is invalid. Stub mode returns a synthetic name.
        """
        account_number = (account_number or "").strip()
        bank_code = (bank_code or "").strip()
        if not account_number or not bank_code:
            raise ValueError("account_number and bank_code are required to verify an account")
        if not self._configured:
            return BankAccountResolution(
                account_number=account_number,
                account_name="TEST ACCOUNT",
                bank_code=bank_code,
            )
        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # GET /bank/resolve?account_number=...&bank_code=... — the
                # registered account name is returned by Paystack; the user
                # never types it.
                resp = await client.get(
                    f"{PAYSTACK_API_BASE}/bank/resolve",
                    params={"account_number": account_number, "bank_code": bank_code},
                    headers=headers,
                )
                data = resp.json()
        except Exception as exc:
            raise ValueError(f"Could not verify bank account: {exc}") from exc
        if resp.status_code != 200 or not data.get("status", False):
            raise ValueError(
                f"Invalid bank account: {data.get('message', 'account could not be resolved')}"
            )
        d = data.get("data", {})
        if not d.get("account_name"):
            raise ValueError("Bank account could not be resolved — check the bank and account number")
        return BankAccountResolution(
            account_number=d.get("account_number", account_number),
            account_name=d.get("account_name", ""),
            bank_code=bank_code,
        )

    async def list_banks(self, country: str = "NG", currency: str = "NGN") -> list[BankInfo]:
        """List Paystack-supported banks.

        Paystack's ``GET /bank`` endpoint takes **no parameters** and returns
        every supported bank; we filter to the requested country/currency
        client-side when those fields are present on each bank record.
        """
        if not self._configured:
            return [
                BankInfo(code="044", name="Access Bank", country="NG", currency="NGN"),
                BankInfo(code="011", name="First Bank", country="NG", currency="NGN"),
                BankInfo(code="058", name="GTBank", country="NG", currency="NGN"),
                BankInfo(code="070", name="Fidelity Bank", country="NG", currency="NGN"),
                BankInfo(code="232", name="Sterling Bank", country="NG", currency="NGN"),
                BankInfo(code="221", name="Stanbic IBTC", country="NG", currency="NGN"),
            ]
        headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # GET /bank takes NO parameters and returns every supported bank.
                resp = await client.get(f"{PAYSTACK_API_BASE}/bank", headers=headers)
                data = resp.json()
        except Exception:
            return []
        # Paystack signals failure with status=false (boolean) OR a 4xx code;
        # some error bodies use status=true with data=null — treat that as empty too.
        if resp.status_code != 200 or data.get("status") is not True:
            return []
        raw = data.get("data")
        if not isinstance(raw, list) or not raw:
            return []
        banks: list[BankInfo] = []
        for b in raw:
            if not isinstance(b, dict):
                continue
            banks.append(
                BankInfo(
                    code=str(b.get("code", "")),
                    name=str(b.get("name", "")),
                    country=str(b.get("country") or country).upper(),
                    currency=str(b.get("currency") or currency).upper(),
                )
            )
        return banks

    async def create_transfer_recipient(
        self,
        account_number: str,
        bank_code: str,
        account_name: str,
        currency: str = "NGN",
    ) -> str | None:
        """Create a Paystack transfer recipient for payouts."""
        if not self._configured:
            return f"RCP_stub_{uuid.uuid4().hex[:16]}"
        body = {
            "type": "nuban",
            "name": account_name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": currency,
        }
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{PAYSTACK_API_BASE}/transferrecipient", json=body, headers=headers
                )
                data = resp.json()
            if resp.status_code not in (200, 201) or not data.get("status", False):
                raise RuntimeError(
                    f"Transfer recipient creation failed: {data.get('message', 'unknown error')}"
                )
            return data.get("data", {}).get("recipient_code")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Transfer recipient creation failed: {exc}") from exc

    async def initiate_transfer(
        self,
        recipient_code: str,
        amount: int,
        currency: str,
        reference: str,
        reason: str = "",
    ) -> str | None:
        """Initiate a Paystack transfer (payout) to a recipient."""
        if not self._configured:
            return f"TRF_stub_{uuid.uuid4().hex[:16]}"
        body = {
            "source": "balance",
            "amount": amount,
            "reference": reference,
            "recipient": recipient_code,
            "reason": reason or "Merchant payout",
            "currency": currency,
        }
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{PAYSTACK_API_BASE}/transfer", json=body, headers=headers
                )
                data = resp.json()
            if resp.status_code not in (200, 201) or not data.get("status", False):
                raise RuntimeError(
                    f"Payout transfer failed: {data.get('message', 'unknown error')}"
                )
            return data.get("data", {}).get("transfer_code") or data.get("data", {}).get("reference")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Payout transfer failed: {exc}") from exc

    async def create_split(
        self,
        name: str,
        legs: list[SplitLeg],
        currency: str,
    ) -> SplitResult | None:
        """Create a Paystack Transaction Split from per-merchant legs.

        Paystack splits take ``subaccounts`` with ``share`` (percent or
        amount); merchant legs reference their subaccount code, the platform
        leg uses the account that owns the transaction. Stub fallback returns
        a deterministic split code in dev/test.
        """
        if not legs:
            return None
        if not self._configured:
            return SplitResult(
                split_code=f"SPL_stub_{uuid.uuid4().hex[:16]}", provider=self.provider_key
            )

        subaccounts = []
        for leg in legs:
            if not leg.subaccount:
                continue  # platform leg — no subaccount
            subaccounts.append({"subaccount": leg.subaccount, "share": leg.amount})

        body: dict = {
            "name": name[:100],
            "type": "flat",
            "currency": currency,
            "subaccounts": subaccounts,
            "bearer_type": "account",  # platform absorbs transaction fees
        }
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{PAYSTACK_API_BASE}/split", json=body, headers=headers
                )
                data = resp.json()
            if resp.status_code not in (200, 201) or not data.get("status", False):
                raise RuntimeError(
                    f"Paystack split creation failed: "
                    f"{data.get('message', 'unknown error')}"
                )
            split_code = data.get("data", {}).get("split_code")
            if not split_code:
                raise RuntimeError(
                    "Paystack split creation succeeded without returning a split code"
                )
            return SplitResult(split_code=split_code, provider=self.provider_key)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Paystack split request failed: {exc}") from exc

    async def initiate_refund(
        self, provider_reference: str, amount: int | None = None
    ) -> bool:
        """Initiate a (partial) refund against a successful transaction."""
        if not self._configured:
            return True  # stub: pretend success
        body: dict = {"transaction": provider_reference}
        if amount is not None:
            body["amount"] = amount
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{PAYSTACK_API_BASE}/refund", json=body, headers=headers
                )
                data = resp.json()
            return resp.status_code in (200, 201) and bool(data.get("status", False))
        except Exception:
            return False

    # ── Stub fallback ─────────────────────────────────────────────────

    def _stub_initialize(
        self,
        order_id: str,
        amount: int,
        currency: str,
        metadata: dict | None,
        buyer_email: str | None = None,
    ) -> PaymentInitResult:
        """Generate a deterministic stub payment when Paystack is not configured.

        The stub ``payment_url`` points at a local backend callback endpoint that
        simulates a successful Paystack redirect + webhook round-trip, then
        bounces the buyer back to the storefront.  This lets the full
        checkout → pay → confirm flow work end-to-end without real API keys.
        The real buyer email is recorded in metadata so the stub flow still
        exercises the customer-address path.
        """
        reference = f"paystack_ord_{order_id}_{uuid.uuid4().hex[:12]}"
        if metadata is None:
            metadata = {}
        if buyer_email:
            metadata = {**metadata, "customer_email": buyer_email}
        # Stub redirect: backend simulates the Paystack webhook, then redirects
        # the buyer back to the frontend order page.
        payment_url = f"{settings.FRONTEND_URL}/pay/stub-callback?ref={reference}"
        return PaymentInitResult(
            provider_reference=reference,
            payment_url=payment_url,
            status="initialized",
        )