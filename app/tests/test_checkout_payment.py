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
from app.models.product import FulfillmentKind, Product, ProductStatus
from app.models.product_variant import ProductVariant
from app.models.store import Store
from app.models.user import Gender, User, UserRole
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
    return {"variant_id": str(variant.id), "product_id": str(product.id)}


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
