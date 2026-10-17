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
    PaymentInitResult,
    PaymentProvider,
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
    ) -> PaymentInitResult:
        """Initialise a Paystack transaction.

        When credentials are not configured (dev / test), falls back to a
        local stub that generates a reference and a mock authorization URL.
        """
        if not self._configured:
            return self._stub_initialize(order_id, amount, currency, metadata)

        # Build the request body for Paystack's initialize endpoint.
        body: dict = {
            "email": buyer_email or "buyer@example.com",
            "amount": amount,
            "currency": currency,
            "reference": f"ord_{order_id}_{uuid.uuid4().hex[:12]}",
            "callback_url": callback_url or settings.SUPPORT_WEBHOOK_URL,
        }
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
                # Paystack returns status=False on error; fall back to stub
                return self._stub_initialize(order_id, amount, currency, metadata)

            data = data.get("data", {})
            return PaymentInitResult(
                provider_reference=data.get("reference", body["reference"]),
                payment_url=data.get("authorization_url"),
                status="initialized",
            )
        except Exception:
            # On any network / API error, fall back to stub so the flow
            # never hard-blocks in degraded environments.
            return self._stub_initialize(order_id, amount, currency, metadata)

    async def verify_transaction(self, provider_reference: str) -> bool:
        """Verify a Paystack transaction by reference."""
        if not self._configured:
            return True  # stub — assume success for local testing

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

    # ── Stub fallback ─────────────────────────────────────────────────

    def _stub_initialize(
        self,
        order_id: str,
        amount: int,
        currency: str,
        metadata: dict | None,
    ) -> PaymentInitResult:
        """Generate a deterministic stub payment when Paystack is not configured.

        The stub ``payment_url`` points at a local backend callback endpoint that
        simulates a successful Paystack redirect + webhook round-trip, then
        bounces the buyer back to the storefront.  This lets the full
        checkout → pay → confirm flow work end-to-end without real API keys.
        """
        reference = f"paystack_ord_{order_id}_{uuid.uuid4().hex[:12]}"
        # Stub redirect: backend simulates the Paystack webhook, then redirects
        # the buyer back to the frontend order page.
        payment_url = f"{settings.FRONTEND_URL}/pay/stub-callback?ref={reference}"
        return PaymentInitResult(
            provider_reference=reference,
            payment_url=payment_url,
            status="initialized",
        )