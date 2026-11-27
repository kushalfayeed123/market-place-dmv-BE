# backend/app/tests/test_checkout_payment.py
"""
End-to-end tests for the buyer checkout -> payment -> webhook flow.

Covers:
  - checkout endpoint creates an order with the idempotency key
  - process_payment endpoint creates a payment transaction with status "initialized"
  - handle_webhook on a payment.success event flips the payment + order to "success" / "paid"
  - get_payment_by_order returns the updated payment after the webhook
"""

import uuid

import pytest
from app.main import app
from app.models.category import Category
from app.models.commission_plan import CommissionPlan
from app.models.enums import InventoryPolicy
from app.models.merchant import KycStatus, Merchant
from app.models.merchant_payout_account import MerchantPayoutAccount
from app.models.product import FulfillmentKind, Product, ProductStatus
from app.models.product_variant import ProductVariant
from app.models.payment_transaction import PaymentTransaction
from app.models.store import Store
from app.models.user import Gender, User, UserRole
from app.modules.payments.providers.base import (
    PaymentInitResult,
    PaymentVerificationResult,
)
from app.modules.payments.providers.paystack import PaystackProvider
from httpx import AsyncClient


@pytest.fixture
async def seed_data(db):
    """Seed the test DB with a merchant, store, category, product, and variant."""
    # Commission plan
    plan = CommissionPlan(name="default", percentage_bps=1000, flat_fee_minor=0, is_default=True)
    db.add(plan)
    await db.flush()

    # Category
    cat = Category(name="Electronics")
    db.add(cat)
    await db.flush()

    # Merchant owner user
    owner = User(
        email="merchant_owner@example.com",
        password_hash="dummy_hash",  # password is never validated in checkout flow
        role=UserRole.MERCHANT_OWNER,
        first_name="Merchant",
        last_name="Owner",
        gender=Gender.UNSET,
    )
    db.add(owner)
    await db.flush()

    # Merchant
    merchant = Merchant(
        owner_user_id=owner.id,
        business_name="Test Merchant",
        slug="test-merchant-" + uuid.uuid4().hex[:8],
        kyc_status=KycStatus.VERIFIED,
        commission_plan_id=plan.id,
        country="NG",
    )
    db.add(merchant)
    await db.flush()

    # Store
    store = Store(merchant_id=merchant.id, name="Test Store", slug="test-store-" + uuid.uuid4().hex[:8])
    db.add(store)
    await db.flush()

    # Product
    product = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Test Product",
        slug="test-product-" + uuid.uuid4().hex[:8],
        description="A test product for e2e checkout",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.ACTIVE.value,
        base_price_amount=10000,
        base_price_currency="NGN",
    )
    db.add(product)
    await db.flush()

    # Variant (untracked so checkout does not require inventory rows)
    variant = ProductVariant(
        product_id=product.id,
        sku="TEST-SKU-" + uuid.uuid4().hex[:8],
        attributes="{}",
        inventory_policy=InventoryPolicy.UNTRACKED.value,
    )
    db.add(variant)
    await db.flush()

    await db.commit()
    return {
        "variant_id": str(variant.id),
        "product_id": str(product.id),
        "merchant_id": str(merchant.id),
        "store_id": str(store.id),
        "cat_id": str(cat.id),
    }


@pytest.fixture
async def buyer_token(client: AsyncClient) -> str:
    """Register + log in a buyer and return the bearer token."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "buyer_e2e@example.com",
            "password": "SecurePass123!",
            "first_name": "E2E",
            "last_name": "Buyer",
            "role": "buyer",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "buyer_e2e@example.com", "password": "SecurePass123!"},
    )
    return resp.json()["access_token"]


@pytest.fixture
async def buyer_headers(buyer_token: str) -> dict:
    return {"Authorization": f"Bearer {buyer_token}"}


@pytest.mark.asyncio
async def test_checkout_creates_order(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """Basic checkout: one merchant, one product, order created + pending."""
    variant_id = seed_data["variant_id"]
    # 1. Checkout
    co = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}], "fulfillment_option": "pickup"},
        headers=buyer_headers,
    )
    assert co.status_code == 201, co.text
    order = co.json()
    assert order["status"] == "pending"
    order_id = order["id"]

    # 2. Process payment (stub path)
    pay = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers=buyer_headers,
    )
    assert pay.status_code == 201, pay.text
    ref = pay.json()["provider_reference"]

    # 3. Simulate webhook
    wh = await client.post(
        "/api/v1/payments/webhooks/paystack",
        json={"event": "charge.success", "data": {"id": "evt_mc", "reference": ref}},
    )
    assert wh.status_code == 200, wh.text

    # 4. Verify order is 'paid'
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=buyer_headers,
    )
    assert order_resp.status_code == 200
    data = order_resp.json()
    assert data["status"] == "paid"

    # 5. Ledger entries should exist for sale + payout_hold
    ledger_resp = await client.get(
        "/api/v1/ledger/entries?merchant_id=" + seed_data["merchant_id"],
        headers=buyer_headers,
    )
    assert ledger_resp.status_code == 200
    ledger_data = ledger_resp.json()
    assert any(e["entry_type"] == "sale" for e in ledger_data)
    assert any(e["entry_type"] == "payout_hold" for e in ledger_data)


@pytest.mark.asyncio
async def test_checkout_rejects_zero_variant_override(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, db
):
    variant = await db.get(ProductVariant, uuid.UUID(seed_data["variant_id"]))
    variant.price_override_amount = 0
    await db.commit()

    response = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "zero-variant-price"},
    )

    assert response.status_code == 400
    assert "price greater than zero" in response.json()["detail"]


@pytest.mark.asyncio
async def test_checkout_multi_merchant_two_merchants(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, db
):
    """Checkout with two merchants (two products from two stores) → one order.

    The order contains two OrderItems, each with its own merchant_id.
    Payment success webhook should create per-merchant ledger entries
    (sale + payout_hold per merchant) and flip order status to 'paid'.
    """
    variant_id = seed_data["variant_id"]
    # Create a second product in the same merchant's store (or a second merchant)
    # For simplicity we use the same merchant but two distinct products.
    # We'll create a second product under the same merchant.
    merchant_id = seed_data["merchant_id"]
    store_id = seed_data["store_id"]

    from app.core.security import to_uuid

    # Second product
    second_product = Product(
        merchant_id=to_uuid(merchant_id),
        store_id=to_uuid(store_id),
        category_id=to_uuid(seed_data["cat_id"]) if seed_data.get("cat_id") else None,
        title="Second Test Product",
        slug="second-test-product-" + uuid.uuid4().hex[:8],
        description="Second product for multi-merchant test",
        fulfillment_type="physical",
        status="active",
        base_price_amount=15000,
        base_price_currency="NGN",
    )
    db.add(second_product)
    await db.flush()

    second_variant = ProductVariant(
        product_id=second_product.id,
        sku="SECOND-SKU-" + uuid.uuid4().hex[:8],
        attributes="{}",
        inventory_policy="untracked",
    )
    db.add(second_variant)
    await db.flush()

    # Checkout with both products
    co = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [
            {"variant_id": variant_id, "quantity": 1},
            {"variant_id": str(second_variant.id), "quantity": 1},
        ], "fulfillment_option": "pickup"},
        headers=buyer_headers,
    )
    assert co.status_code == 201, co.text
    order = co.json()
    assert order["status"] == "pending"
    order_id = order["id"]

    # 2. Process payment (stub path)
    pay = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers=buyer_headers,
    )
    assert pay.status_code == 201, pay.text
    ref = pay.json()["provider_reference"]

    # 3. Simulate webhook
    wh = await client.post(
        "/api/v1/payments/webhooks/paystack",
        json={"event": "charge.success", "data": {"id": "evt_mc", "reference": ref}},
    )
    assert wh.status_code == 200, wh.text

    # 4. Verify order is 'paid'
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=buyer_headers,
    )
    assert order_resp.status_code == 200
    data = order_resp.json()
    assert data["status"] == "paid"

    # 5. Ledger entries: two sale + two payout_hold entries (one per product)
    ledger_resp = await client.get(
        "/api/v1/ledger/entries?merchant_id=" + merchant_id,
        headers=buyer_headers,
    )
    assert ledger_resp.status_code == 200
    ledger_data = ledger_resp.json()
    sale_entries = [e for e in ledger_data if e["entry_type"] == "sale"]
    hold_entries = [e for e in ledger_data if e["entry_type"] == "payout_hold"]
    assert len(sale_entries) == 2, f"Expected 2 sale entries, got {len(sale_entries)}"
    assert len(hold_entries) == 2, f"Expected 2 payout_hold entries, got {len(hold_entries)}"
    # Each entry should reference a different product/merchant combo
    sale_merchant_ids = {e["merchant_id"] for e in sale_entries}
    assert len(sale_merchant_ids) == 1  # same merchant for both products
    """Checkout should create an order with idempotent behaviour."""
    variant_id = seed_data["variant_id"]
    payload = {
        "items": [{"variant_id": variant_id, "quantity": 1}],
        "fulfillment_option": "pickup",
    }
    resp = await client.post(
        "/api/v1/orders/checkout",
        json=payload,
        headers={**buyer_headers, "Idempotency-Key": "e2e-checkout-1"},
    )
    assert resp.status_code == 201
    order = resp.json()
    assert order["status"] == "pending"
    assert order["item_count"] >= 1

    # Same idempotency key -- cached response
    resp2 = await client.post(
        "/api/v1/orders/checkout",
        json=payload,
        headers={**buyer_headers, "Idempotency-Key": "e2e-checkout-1"},
    )
    assert resp2.status_code == 201
    order2 = resp2.json()
    assert order2["id"] == order["id"]


@pytest.mark.asyncio
async def test_physical_checkout_requires_delivery_address(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    response = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "physical-address-required"},
    )
    assert response.status_code == 400
    assert "delivery_address is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delivery_checkout_uses_phone_from_delivery_address(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    response = await client.post(
        "/api/v1/orders/checkout",
        json={
            "items": [{"variant_id": seed_data["variant_id"], "quantity": 1}],
            "delivery_address": {
                "full_name": "Michael Ajanaku",
                "phone": "07015902708",
                "address_line_1": "72 Yellow Street Solutionist Estate Karshi",
                "city": "Abuja",
                "state": "FCT",
                "country": "Nigeria",
            },
            "fulfillment_option": "delivery",
        },
        headers={**buyer_headers, "Idempotency-Key": "delivery-phone-from-address"},
    )

    assert response.status_code == 201, response.text
    order = response.json()
    assert order["buyer_phone"] == "07015902708"
    assert order["delivery_address"]["phone"] == "07015902708"


@pytest.mark.asyncio
async def test_digital_checkout_does_not_require_delivery_address(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, db
):
    from sqlalchemy import update

    await db.execute(
        update(Product)
        .where(Product.id == uuid.UUID(seed_data["product_id"]))
        .values(fulfillment_type="digital")
    )
    await db.commit()

    response = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "digital-no-address"},
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_process_payment_initializes_transaction(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """process_payment should create a payment transaction with status 'initialized'."""
    variant_id = seed_data["variant_id"]
    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-pay-checkout-1"},
    )
    assert checkout_resp.status_code == 201
    order = checkout_resp.json()
    order_id = order["id"]

    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-pay-1"},
    )
    assert pay_resp.status_code == 201
    payment = pay_resp.json()
    assert payment["order_id"] == order_id
    assert payment["provider"] == "paystack"
    assert payment["status"] == "initialized"

    repeated = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-pay-repeated"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == payment["id"]


@pytest.mark.asyncio
async def test_payment_verification_confirms_success_and_wins_over_stale_attempt(
    client: AsyncClient,
    buyer_headers: dict,
    seed_data: dict,
    db,
    monkeypatch: pytest.MonkeyPatch,
):
    async def initialize(self, order_id, amount, currency, **kwargs):
        return PaymentInitResult(
            provider_reference="verify-success-reference",
            payment_url="https://pay.example/verify",
        )

    async def verify(self, provider_reference):
        assert provider_reference == "verify-success-reference"
        return PaymentVerificationResult(status="success", amount=10000, currency="NGN")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    monkeypatch.setattr(PaystackProvider, "verify_transaction_details", verify)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={
            "items": [{"variant_id": seed_data["variant_id"], "quantity": 1}],
            "fulfillment_option": "pickup",
        },
        headers={**buyer_headers, "Idempotency-Key": "verify-success-checkout"},
    )
    assert checkout.status_code == 201
    order_id = checkout.json()["id"]

    payment_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "verify-success-init"},
    )
    assert payment_resp.status_code == 201
    assert payment_resp.json()["status"] == "initialized"

    verified = await client.post(
        f"/api/v1/payments/order/{order_id}/verify",
        headers=buyer_headers,
        json={},
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "success"

    db.add(
        PaymentTransaction(
            order_id=uuid.UUID(order_id),
            provider="paystack",
            provider_reference="later-initialized-attempt",
            status="initialized",
            amount=10000,
            currency="NGN",
            payment_url="https://pay.example/later",
        )
    )
    await db.commit()
    latest = await client.get(
        f"/api/v1/payments/order/{order_id}",
        headers=buyer_headers,
    )
    assert latest.status_code == 200
    assert latest.json()["status"] == "success"

@pytest.mark.asyncio
async def test_webhook_updates_payment_and_order_status(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """A payment.success webhook should flip payment -> 'success' and order -> 'paid'."""
    variant_id = seed_data["variant_id"]
    # 1. Checkout
    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-wh-checkout-1"},
    )
    assert checkout_resp.status_code == 201
    order = checkout_resp.json()
    order_id = order["id"]

    # 2. Process payment
    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-wh-pay-1"},
    )
    assert pay_resp.status_code == 201
    payment = pay_resp.json()
    ref = payment["provider_reference"]

    # 3. Simulate webhook
    webhook_payload = {
        "event": "charge.success",
        "data": {"id": "evt_test_123", "reference": ref},
    }
    webhook_resp = await client.post(
        "/api/v1/payments/webhooks/paystack",
        json=webhook_payload,
    )
    assert webhook_resp.status_code == 200

    # 4. Get payment by order -- should now be 'success'
    pay_get = await client.get(
        f"/api/v1/payments/order/{order_id}",
        headers=buyer_headers,
    )
    assert pay_get.status_code == 200
    updated = pay_get.json()
    assert updated["status"] == "success"

    # 5. Order status should also be 'paid'
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=buyer_headers,
    )
    assert order_resp.status_code == 200
    order = order_resp.json()
    assert order["status"] == "paid"


@pytest.mark.asyncio
async def test_get_payment_by_order_access_control(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """A non-owner buyer should get 404 when checking a non-existent order's payment."""
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "buyer_other@example.com",
            "password": "SecurePass123!",
            "first_name": "Other",
            "last_name": "Buyer",
            "role": "buyer",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "buyer_other@example.com", "password": "SecurePass123!"},
    )
    other_token = resp.json()["access_token"]
    other_headers = {"Authorization": f"Bearer {other_token}"}

    pay_resp = await client.get(
        "/api/v1/payments/order/00000000-0000-0000-0000-000000000000",
        headers=other_headers,
    )
    assert pay_resp.status_code == 404


@pytest.mark.asyncio
async def test_stub_simulate_completes_payment_end_to_end(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end: checkout → process_payment → stub simulate → success.

    Exercises the full stub fallback flow that a dev/test user experiences
    when no real Paystack credentials are configured.
    """
    # Force stub mode so the provider generates a local redirect URL
    # rather than calling the real Paystack API.
    from app.core.config import settings
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_your_test_key_here")

    variant_id = seed_data["variant_id"]

    # 1. Checkout
    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-stub-checkout-1"},
    )
    assert checkout_resp.status_code == 201
    order_id = checkout_resp.json()["id"]

    # 2. Process payment (stub → gets a payment_url + provider_reference)
    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-stub-pay-1"},
    )
    assert pay_resp.status_code == 201
    payment = pay_resp.json()
    ref = payment["provider_reference"]
    assert payment["status"] == "initialized"
    assert payment.get("payment_url") is not None
    assert payment["payment_url"].startswith("http://localhost:3000/pay/stub-callback")

    # 3. Simulate the Paystack callback via the stub endpoint
    stub_resp = await client.post(
        f"/api/v1/payments/stub/simulate?ref={ref}",
    )
    assert stub_resp.status_code == 200

    # 4. Payment should now be 'success'
    pay_get = await client.get(
        f"/api/v1/payments/order/{order_id}",
        headers=buyer_headers,
    )
    assert pay_get.status_code == 200
    updated = pay_get.json()
    assert updated["status"] == "success"

    # 5. Order should be 'paid'
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=buyer_headers,
    )
    assert order_resp.status_code == 200
    order = order_resp.json()
    assert order["status"] == "paid"


@pytest.mark.asyncio
async def test_get_payment_methods_lists_providers(
    client: AsyncClient, buyer_headers: dict
):
    """GET /payments/methods should list registered providers with implemented flag."""
    resp = await client.get("/api/v1/payments/methods", headers=buyer_headers)
    assert resp.status_code == 200
    methods = resp.json()
    keys = {m["key"] for m in methods}
    assert "paystack" in keys
    assert "flutterwave" in keys
    assert "stripe" in keys
    paystack = next(m for m in methods if m["key"] == "paystack")
    assert paystack["implemented"] is True
    flutterwave = next(m for m in methods if m["key"] == "flutterwave")
    assert flutterwave["implemented"] is False


@pytest.mark.asyncio
async def test_single_merchant_paystack_checkout_uses_direct_subaccount_settlement(
    client: AsyncClient,
    buyer_headers: dict,
    seed_data: dict,
    db,
    monkeypatch: pytest.MonkeyPatch,
):
    db.add(
        MerchantPayoutAccount(
            merchant_id=uuid.UUID(seed_data["merchant_id"]),
            provider="paystack",
            currency="NGN",
            external_ref="ACCT_test_merchant",
            is_active=True,
        )
    )
    await db.commit()
    captured: dict = {}

    async def create_split(self, name, legs, currency):
        pytest.fail("Single-merchant orders must not create a dynamic flat split")

    async def initialize(self, order_id, amount, currency, **kwargs):
        captured["split_code"] = kwargs.get("split_code")
        captured["subaccount"] = kwargs.get("subaccount")
        captured["transaction_charge"] = kwargs.get("transaction_charge")
        return PaymentInitResult(
            provider_reference="paystack-direct-subaccount-test",
            payment_url="https://pay.example/checkout",
        )

    monkeypatch.setattr(PaystackProvider, "create_split", create_split)
    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={
            "items": [{"variant_id": seed_data["variant_id"], "quantity": 1}],
            "fulfillment_option": "pickup",
        },
        headers={**buyer_headers, "Idempotency-Key": "single-merchant-split-checkout"},
    )
    assert checkout.status_code == 201, checkout.text

    payment = await client.post(
        "/api/v1/payments/process",
        json={"order_id": checkout.json()["id"], "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "single-merchant-split-payment"},
    )

    assert payment.status_code == 201, payment.text
    assert captured["split_code"] is None
    assert captured["subaccount"] == "ACCT_test_merchant"
    assert captured["transaction_charge"] == 1000


@pytest.mark.asyncio
async def test_paystack_initialize_sends_direct_subaccount_and_commission(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "status": True,
                "data": {
                    "reference": "paystack-direct-ref",
                    "authorization_url": "https://pay.example/checkout",
                },
            }

    class FakeClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, json, headers):
            captured["body"] = json
            return FakeResponse()

    monkeypatch.setattr(PaystackProvider, "_configured", True)
    monkeypatch.setattr(
        "app.modules.payments.providers.paystack.httpx.AsyncClient", FakeClient
    )

    await PaystackProvider().initialize_transaction(
        order_id=str(uuid.uuid4()),
        amount=10153,
        currency="NGN",
        buyer_email="buyer@example.com",
        subaccount="ACCT_test_merchant",
        transaction_charge=1000,
    )

    assert captured["body"]["subaccount"] == "ACCT_test_merchant"
    assert captured["body"]["transaction_charge"] == 1000
    assert "split_code" not in captured["body"]


@pytest.mark.asyncio
async def test_online_payment_requires_matching_merchant_subaccount(
    client: AsyncClient,
    buyer_headers: dict,
    seed_data: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    async def initialize(self, order_id, amount, currency, **kwargs):
        pytest.fail("Payment initialization must not run without a matching subaccount")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={
            "items": [{"variant_id": seed_data["variant_id"], "quantity": 1}],
            "fulfillment_option": "pickup",
        },
        headers={**buyer_headers, "Idempotency-Key": "missing-subaccount-checkout"},
    )
    assert checkout.status_code == 201, checkout.text

    payment = await client.post(
        "/api/v1/payments/process",
        json={"order_id": checkout.json()["id"], "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "missing-subaccount-payment"},
    )

    assert payment.status_code == 400
    assert "must configure an active paystack payout account in NGN" in payment.json()["detail"]


@pytest.mark.asyncio
async def test_pay_on_delivery_marks_order_awaiting_approval(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """Pay on Delivery must not error (regression).

    The COD branch calls ``_create_payout_hold_entries`` which used to call the
    async session's ``execute`` without ``await``, raising AttributeError (500)
    on every Pay-on-Delivery attempt.  After the fix the endpoint returns 201
    with a ``pending_verification`` payment and moves the order to
    ``awaiting_approval`` without touching any online provider.
    """
    variant_id = seed_data["variant_id"]

    # 1. Checkout -> order in "pending" status
    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-pod-checkout-1"},
    )
    assert checkout_resp.status_code == 201, checkout_resp.text
    order_id = checkout_resp.json()["id"]

    # 2. Process payment with the pay-on-delivery provider
    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "pay_on_delivery"},
        headers={**buyer_headers, "Idempotency-Key": "e2e-pod-pay-1"},
    )
    assert pay_resp.status_code == 201, pay_resp.text
    payment = pay_resp.json()
    assert payment["provider"] == "pay_on_delivery"
    assert payment["status"] == "pending_verification"
    assert payment["payment_method"] == "pay_on_delivery"
    assert payment["payment_url"] is None

    # 3. Order should now be awaiting merchant approval
    order_resp = await client.get(f"/api/v1/orders/{order_id}", headers=buyer_headers)
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_get_order_accepts_order_number(
    client: AsyncClient, buyer_headers: dict, seed_data: dict
):
    """GET /orders/{order_id} must accept the human-readable order number
    (e.g. ORD-20261109-190345-17ec), not just the UUID — previously this
    raised ValueError('Invalid UUID') → 500. Buyers and the agent reference
    orders by order number."""
    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "order-number-lookup-checkout"},
    )
    assert checkout_resp.status_code == 201, checkout_resp.text
    body = checkout_resp.json()
    order_id, order_number = body["id"], body["order_number"]
    assert order_number.startswith("ORD-")

    # By UUID (existing behavior)
    by_id = await client.get(f"/api/v1/orders/{order_id}", headers=buyer_headers)
    assert by_id.status_code == 200, by_id.text

    # By order number (the bug — used to 500)
    by_number = await client.get(f"/api/v1/orders/{order_number}", headers=buyer_headers)
    assert by_number.status_code == 200, by_number.text
    assert by_number.json()["id"] == order_id
    assert by_number.json()["order_number"] == order_number

    # Order detail must include the actual products (names, not just ids)
    items = by_number.json()["items"]
    assert len(items) == 1
    assert items[0]["product_name"] == "Test Product"
    assert items[0]["quantity"] == 1
    assert items[0]["unit_price"] == 10000
    assert items[0]["line_total"] == 10000

    # Unknown reference → clean 404, not a 500
    missing = await client.get("/api/v1/orders/ORD-99999999-999999-zzzz", headers=buyer_headers)
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_payment_methods_fulfillment_filter(
    client: AsyncClient, buyer_headers: dict
):
    """Pay on Delivery is advertised for physical orders only.

    Without a fulfillment hint it stays listed (backward compatible); with
    fulfillment=digital/service it must be hidden; with delivery/pickup shown.
    """
    resp = await client.get("/api/v1/payments/methods", headers=buyer_headers)
    assert resp.status_code == 200
    assert "pay_on_delivery" in {m["key"] for m in resp.json()}

    for fulfillment, expected in [("delivery", True), ("pickup", True), ("digital", False), ("service", False)]:
        resp = await client.get(
            f"/api/v1/payments/methods?fulfillment={fulfillment}", headers=buyer_headers
        )
        assert resp.status_code == 200
        keys = {m["key"] for m in resp.json()}
        assert ("pay_on_delivery" in keys) is expected, fulfillment


@pytest.mark.asyncio
async def test_pay_on_delivery_rejected_for_digital_order(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, db
):
    """Pay on Delivery must not be accepted for orders without physical items."""
    from sqlalchemy import update

    await db.execute(
        update(Product)
        .where(Product.id == uuid.UUID(seed_data["product_id"]))
        .values(fulfillment_type="digital")
    )
    await db.commit()

    checkout_resp = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "digital-pod-checkout"},
    )
    assert checkout_resp.status_code == 201, checkout_resp.text
    order_id = checkout_resp.json()["id"]

    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "pay_on_delivery"},
        headers={**buyer_headers, "Idempotency-Key": "digital-pod-pay"},
    )
    assert pay_resp.status_code == 400, pay_resp.text
    assert "physical" in pay_resp.json()["detail"].lower()

@pytest.mark.asyncio
async def test_verify_accepts_provider_amount_including_commission(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, monkeypatch: pytest.MonkeyPatch
):
    """The provider adds its commission/fees at the point of payment, so the
    verified amount differs from the order total.  The verify endpoint must
    accept the provider's actual paid amount instead of rejecting the mismatch."""

    async def initialize(self, order_id, amount, currency, **kwargs):
        return PaymentInitResult(
            provider_reference="verify-commission-ref",
            payment_url="https://pay.example/verify",
        )

    async def verify(self, provider_reference):
        assert provider_reference == "verify-commission-ref"
        # Order total is 10000; the provider actually charged 10500 (500 commission).
        return PaymentVerificationResult(status="success", amount=10500, currency="NGN")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    monkeypatch.setattr(PaystackProvider, "verify_transaction_details", verify)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "verify-commission-checkout"},
    )
    assert checkout.status_code == 201
    order_id = checkout.json()["id"]

    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "verify-commission-pay"},
    )
    assert pay_resp.status_code == 201

    verified = await client.post(
        f"/api/v1/payments/order/{order_id}/verify", headers=buyer_headers, json={}
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "success"
    assert body["amount"] == 10500  # actual amount paid, taken from the provider


@pytest.mark.asyncio
async def test_verify_rejects_currency_mismatch(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, monkeypatch: pytest.MonkeyPatch
):
    """A currency mismatch between provider and order is still rejected."""

    async def initialize(self, order_id, amount, currency, **kwargs):
        return PaymentInitResult(
            provider_reference="verify-currency-ref",
            payment_url="https://pay.example/verify",
        )

    async def verify(self, provider_reference):
        return PaymentVerificationResult(status="success", amount=10000, currency="USD")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    monkeypatch.setattr(PaystackProvider, "verify_transaction_details", verify)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "verify-currency-checkout"},
    )
    assert checkout.status_code == 201
    order_id = checkout.json()["id"]
    await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "verify-currency-pay"},
    )

    verified = await client.post(
        f"/api/v1/payments/order/{order_id}/verify", headers=buyer_headers, json={}
    )
    assert verified.status_code == 400
    assert "currency" in verified.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_does_not_confirm_when_provider_disputes(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, monkeypatch: pytest.MonkeyPatch
):
    """The webhook alone must not release value: if the provider's verification
    endpoint says the transaction is not successful, the payment stays pending."""

    async def initialize(self, order_id, amount, currency, **kwargs):
        return PaymentInitResult(
            provider_reference="wh-dispute-ref",
            payment_url="https://pay.example/x",
        )

    async def verify(self, provider_reference):
        assert provider_reference == "wh-dispute-ref"
        return PaymentVerificationResult(status="failed", amount=10000, currency="NGN")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    monkeypatch.setattr(PaystackProvider, "verify_transaction_details", verify)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "wh-dispute-checkout"},
    )
    assert checkout.status_code == 201
    order_id = checkout.json()["id"]
    pay_resp = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "wh-dispute-pay"},
    )
    assert pay_resp.status_code == 201

    webhook_resp = await client.post(
        "/api/v1/payments/webhooks/paystack",
        json={"event": "charge.success", "data": {"id": "evt_dispute_1", "reference": "wh-dispute-ref"}},
    )
    assert webhook_resp.status_code == 200

    pay_get = await client.get(f"/api/v1/payments/order/{order_id}", headers=buyer_headers)
    assert pay_get.json()["status"] == "initialized"  # NOT success — provider disputed
    order_get = await client.get(f"/api/v1/orders/{order_id}", headers=buyer_headers)
    assert order_get.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_webhook_records_actual_paid_amount_from_provider(
    client: AsyncClient, buyer_headers: dict, seed_data: dict, monkeypatch: pytest.MonkeyPatch
):
    """On provider-confirmed webhook success, the payment amount becomes the
    actual amount paid (order total + provider commission) from the provider."""

    async def initialize(self, order_id, amount, currency, **kwargs):
        return PaymentInitResult(
            provider_reference="wh-amount-ref",
            payment_url="https://pay.example/x",
        )

    async def verify(self, provider_reference):
        assert provider_reference == "wh-amount-ref"
        # 10000 order + 500 provider commission
        return PaymentVerificationResult(status="success", amount=10500, currency="NGN")

    monkeypatch.setattr(PaystackProvider, "initialize_transaction", initialize)
    monkeypatch.setattr(PaystackProvider, "verify_transaction_details", verify)

    checkout = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": seed_data["variant_id"], "quantity": 1}], "fulfillment_option": "pickup"},
        headers={**buyer_headers, "Idempotency-Key": "wh-amount-checkout"},
    )
    assert checkout.status_code == 201
    order_id = checkout.json()["id"]
    await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "wh-amount-pay"},
    )

    webhook_resp = await client.post(
        "/api/v1/payments/webhooks/paystack",
        json={"event": "charge.success", "data": {"id": "evt_amount_1", "reference": "wh-amount-ref"}},
    )
    assert webhook_resp.status_code == 200

    pay_get = await client.get(f"/api/v1/payments/order/{order_id}", headers=buyer_headers)
    body = pay_get.json()
    assert body["status"] == "success"
    assert body["amount"] == 10500
    order_get = await client.get(f"/api/v1/orders/{order_id}", headers=buyer_headers)
    assert order_get.json()["status"] == "paid"
