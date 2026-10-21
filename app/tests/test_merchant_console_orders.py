# backend/app/tests/test_merchant_console_orders.py
"""
End-to-end tests for the merchant console order-management flow.

Covers:
  - buyer checkout -> payment -> webhook (order becomes "paid")
  - merchant owner listing orders via /merchants/{id}/orders
  - merchant owner performing accept / ship / cancel actions on orders
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from uuid import uuid4

from app.core.security import get_password_hash, to_uuid
from app.models.category import Category
from app.models.commission_plan import CommissionPlan
from app.models.enums import InventoryPolicy
from app.models.inventory import Inventory
from app.models.ledger_entry import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.merchant import KycStatus, Merchant
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.product import FulfillmentKind, Product, ProductStatus
from app.models.product_variant import ProductVariant
from app.models.store import Store
from app.models.user import Gender, User, UserRole

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def merchant_setup(db) -> dict:
    """Create a merchant owner, buyer, merchant, store, category, product, variant."""
    plan = CommissionPlan(
        name="default", percentage_bps=1000, flat_fee_minor=0, is_default=True
    )
    db.add(plan)
    await db.flush()

    cat = Category(name="Electronics")
    db.add(cat)
    await db.flush()

    owner = User(
        email="merchant_owner_mc@example.com",
        password_hash=get_password_hash("MerchantPass123!"),
        role=UserRole.MERCHANT_OWNER,
        first_name="Merchant",
        last_name="Owner",
        gender=Gender.UNSET,
    )
    db.add(owner)
    await db.flush()

    merchant = Merchant(
        owner_user_id=owner.id,
        business_name="Test Merchant MC",
        slug="test-merchant-mc-" + owner.id.hex[:8],
        kyc_status=KycStatus.VERIFIED,
        commission_plan_id=plan.id,
        country="NG",
    )
    db.add(merchant)
    await db.flush()

    store = Store(
        merchant_id=merchant.id,
        name="Test Store MC",
        slug="test-store-mc-" + owner.id.hex[:8],
    )
    db.add(store)
    await db.flush()

    product = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Test Product MC",
        slug="test-product-mc-" + owner.id.hex[:8],
        description="A test product for merchant console e2e",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.ACTIVE.value,
        base_price_amount=10000,
        base_price_currency="NGN",
    )
    db.add(product)
    await db.flush()

    variant = ProductVariant(
        product_id=product.id,
        sku="TEST-SKU-MC-" + owner.id.hex[:8],
        attributes="{}",
        inventory_policy=InventoryPolicy.UNTRACKED.value,
    )
    db.add(variant)
    await db.flush()

    buyer = User(
        email="merchant_buyer_mc@example.com",
        password_hash=get_password_hash("BuyerPass123!"),
        role=UserRole.BUYER,
        first_name="Test",
        last_name="Buyer",
        gender=Gender.UNSET,
    )
    db.add(buyer)
    await db.commit()

    return {
        "merchant_id": str(merchant.id),
        "owner_id": str(owner.id),
        "owner_email": owner.email,
        "owner_password": "MerchantPass123!",
        "buyer_email": buyer.email,
        "buyer_password": "BuyerPass123!",
        "variant_id": str(variant.id),
    }


@pytest.fixture
async def buyer_token(client: AsyncClient, merchant_setup: dict) -> str:
    """Log in as the buyer and return the bearer token."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": merchant_setup["buyer_email"],
            "password": merchant_setup["buyer_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
async def merchant_owner_token(client: AsyncClient, merchant_setup: dict) -> str:
    """Log in as the merchant owner and return the bearer token."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": merchant_setup["owner_email"],
            "password": merchant_setup["owner_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
async def paid_order(
    client: AsyncClient, buyer_token: str, merchant_setup: dict
) -> dict:
    """Buyer checks out, payment is processed, webhook confirms -> order is 'paid'."""
    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = merchant_setup["variant_id"]

    # 1. Checkout
    co = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "mc-checkout-1"},
    )
    assert co.status_code == 201, co.text
    order = co.json()
    order_id = order["id"]
    assert order["status"] == "pending"

    # 2. Process payment
    pay = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "mc-pay-1"},
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
    assert order_resp.json()["status"] == "paid"

    return {"order_id": order_id, "order_number": order["order_number"]}


@pytest.fixture
async def pending_order(
    client: AsyncClient, buyer_token: str, merchant_setup: dict
) -> dict:
    """Buyer checks out and initiates a Paystack payment that is NOT confirmed
    by the webhook yet — the order stays 'pending' (unpaid)."""
    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}
    variant_id = merchant_setup["variant_id"]

    # 1. Checkout -> order is 'pending'
    co = await client.post(
        "/api/v1/orders/checkout",
        json={"items": [{"variant_id": variant_id, "quantity": 1}]},
        headers={**buyer_headers, "Idempotency-Key": "mc-checkout-pending"},
    )
    assert co.status_code == 201, co.text
    order = co.json()
    order_id = order["id"]
    assert order["status"] == "pending"

    # 2. Initiate Paystack payment — order remains 'pending' until the webhook fires
    pay = await client.post(
        "/api/v1/payments/process",
        json={"order_id": order_id, "provider": "paystack"},
        headers={**buyer_headers, "Idempotency-Key": "mc-pay-pending"},
    )
    assert pay.status_code == 201, pay.text

    # 3. Confirm still 'pending' (no webhook fired)
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=buyer_headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "pending"

    return {"order_id": order_id, "order_number": order["order_number"]}


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merchant_list_orders_paid(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Merchant owner can list orders; order should appear with status 'paid'."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}

    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/orders",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()
    assert isinstance(orders, list)
    assert len(orders) == 1
    order = orders[0]
    assert order["id"] == paid_order["order_id"]
    assert order["status"] == "paid"
    assert order["number"] == paid_order["order_number"]
    assert order["currency"] == "NGN"
    assert order["total"] == 10000
    assert order["customer_name"]  # non-empty


@pytest.mark.asyncio
async def test_merchant_can_accept_order(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Merchant owner accepts a paid order -> status becomes 'partially_fulfilled'."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]

    resp = await client.post(
        f"/api/v1/orders/{order_id}/accept",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "partially_fulfilled"

    # Verify via GET order
    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "partially_fulfilled"


@pytest.mark.asyncio
async def test_merchant_can_ship_order(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Merchant owner ships an order -> status becomes 'fulfilled'."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]

    # Ship directly from 'paid' (ship_order allows paid OR partially_fulfilled)
    resp = await client.post(
        f"/api/v1/orders/{order_id}/ship",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "fulfilled"

    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "fulfilled"


@pytest.mark.asyncio
async def test_merchant_can_accept_then_ship(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Full flow: accept (paid -> partially_fulfilled) then ship (-> fulfilled)."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]

    # Accept
    acc = await client.post(f"/api/v1/orders/{order_id}/accept", headers=headers)
    assert acc.status_code == 200, acc.text
    assert acc.json()["status"] == "partially_fulfilled"

    # Ship
    ship = await client.post(f"/api/v1/orders/{order_id}/ship", headers=headers)
    assert ship.status_code == 200, ship.text
    assert ship.json()["status"] == "fulfilled"


@pytest.mark.asyncio
async def test_merchant_can_cancel_order(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Merchant owner cancels a paid order -> status becomes 'cancelled'."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]

    resp = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "cancelled"

    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_merchant_can_confirm_payment_from_pending(
    client: AsyncClient,
    merchant_owner_token: str,
    pending_order: dict,
):
    """A merchant can confirm payment for an unpaid (pending) order -> 'paid'.

    Online-payment orders sit in 'pending' until the provider webhook fires.
    The merchant can manually 'Confirm payment' to move such an order to 'paid'
    (e.g. a bank-transfer/cash confirmation the webhook never observed), after
    which the normal Accept -> Ship flow becomes available.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = pending_order["order_id"]

    resp = await client.post(
        f"/api/v1/orders/{order_id}/approve",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"

    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "paid"


@pytest.mark.asyncio
async def test_merchant_can_cancel_unpaid_pending_order(
    client: AsyncClient,
    merchant_owner_token: str,
    pending_order: dict,
):
    """A merchant can cancel an unpaid (pending) order -> 'cancelled'.

    No money has been captured for a pending order, so this is a plain cancel
    with no refund — the 'Cancel order' action for unpaid orders.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = pending_order["order_id"]

    resp = await client.post(
        f"/api/v1/orders/{order_id}/cancel",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "cancelled"

    order_resp = await client.get(
        f"/api/v1/orders/{order_id}",
        headers=headers,
    )
    assert order_resp.status_code == 200
    assert order_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_merchant_order_ownership_enforced(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """A non-owner buyer cannot accept the order."""
    # Register an intruder and try to accept
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "intruder@example.com",
            "password": "IntruderPass123!",
            "role": "buyer",
            "first_name": "Intruder",
            "last_name": "Bad",
        },
    )
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    order_id = paid_order["order_id"]
    resp = await client.post(
        f"/api/v1/orders/{order_id}/accept",
        headers=headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_merchant_cannot_accept_already_accepted(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """Accepting an already-accepted order should return 400."""
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]

    # First accept succeeds
    acc1 = await client.post(f"/api/v1/orders/{order_id}/accept", headers=headers)
    assert acc1.status_code == 200, acc1.text

    # Second accept should fail (status is now partially_fulfilled, not paid)
    acc2 = await client.post(f"/api/v1/orders/{order_id}/accept", headers=headers)
    assert acc2.status_code == 400, acc2.text


# ── Dashboard entry-point tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_me_returns_serialized_role(
    client: AsyncClient,
    merchant_owner_token: str,
):
    """GET /me must return role as a plain string value (e.g. 'merchant_owner'),
    not the enum repr 'UserRole.MERCHANT_OWNER'.

    This is the root-cause fix for the frontend MerchantRouteGuard / role check:
    the guard does ``MERCHANT_ROLES.has(user.role)`` where
    ``MERCHANT_ROLES = new Set(["merchant_owner", "merchant_staff"])``.
    If the backend serialises the enum with ``str()`` instead of ``.value``,
    the role would be ``"UserRole.MERCHANT_OWNER"`` and the guard would
    redirect the merchant to the marketplace — hiding the entire dashboard
    including the order action column.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    user = resp.json()
    assert user["role"] == "merchant_owner"
    assert user["role"] != "UserRole.MERCHANT_OWNER"
    assert user["email"] == "merchant_owner_mc@example.com"
    assert "id" in user
    assert "status" in user


@pytest.mark.asyncio
async def test_login_returns_serialized_role(
    client: AsyncClient,
    merchant_setup: dict,
):
    """Login (and register) must put a plain string role in the TokenResponse.user dict.

    The frontend ``normalizeUser()`` reads ``raw.role`` directly from the
    ``TokenResponse.user`` dict. If the role is an Enum repr instead of the
    string value, ``MerchantRouteGuard`` silently redirects to ``/``.
    """
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": merchant_setup["owner_email"],
            "password": merchant_setup["owner_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    user = data["user"]
    assert user["role"] == "merchant_owner"
    assert user["role"] != "UserRole.MERCHANT_OWNER"


@pytest.mark.asyncio
async def test_merchant_by_owner_returns_serialized_kyc(
    client: AsyncClient,
    merchant_owner_token: str,
    merchant_setup: dict,
):
    """GET /merchants/by-owner/{user_id} must return kyc_status as 'verified',
    not 'KycStatus.VERIFIED'.

    The frontend passes ``merchant.kyc_status`` straight into the
    ``MerchantNavHeader`` KYC badge, which checks
    ``kycStatus === "verified"``. If the enum is serialised with ``str()``
    the badge check fails and the dashboard section renders incorrectly.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    resp = await client.get(
        f"/api/v1/merchants/by-owner/{merchant_setup['owner_id']}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    merchant = resp.json()
    assert merchant["kyc_status"] == "verified"
    assert merchant["kyc_status"] != "KycStatus.VERIFIED"
    assert merchant["business_name"] == "Test Merchant MC"
    assert merchant["owner_user_id"] == merchant_setup["owner_id"]


@pytest.mark.asyncio
async def test_merchant_attention_counts(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """GET /merchants/{id}/attention returns correct counts for the dashboard
    'needs-attention' strip.

    With one paid order that hasn't been accepted/shipped, the
    ``orders_to_fulfil`` count should be 1.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/attention",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    attention = resp.json()
    assert attention["orders_to_fulfil"] == 1
    assert attention["disputes_due"] == 0
    assert attention["unread_messages"] == 0
    assert isinstance(attention["low_stock"], int)


@pytest.mark.asyncio
async def test_merchant_orders_list_shows_paid_status(
    client: AsyncClient,
    merchant_owner_token: str,
    paid_order: dict,
    merchant_setup: dict,
):
    """GET /merchants/{id}/orders returns items with status='paid'.

    The frontend ``sections.ts`` ``when()`` predicates check
    ``r.status === 'paid'`` to decide whether to render the
    'Accept' and 'Cancel & refund' buttons.  If the status comes back as
    'OrderStatus.PAID' instead of 'paid', the action column renders nothing.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/orders",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()
    assert len(orders) == 1
    order = orders[0]
    assert order["status"] == "paid"
    assert order["status"] != "OrderStatus.PAID"
    assert "id" in order
    assert order["id"]


@pytest.mark.asyncio
async def test_full_merchant_dashboard_flow(
    client: AsyncClient,
    merchant_setup: dict,
    paid_order: dict,
):
    """Full end-to-end merchant dashboard flow.

    1. Login as merchant owner → verify role is 'merchant_owner' (string)
    2. GET /merchants/by-owner/{user_id} → load merchant for the dashboard
    3. GET /merchants/{id}/attention → verify one order needs fulfilment
    4. GET /merchants/{id}/orders → verify order status is 'paid'
    5. POST /orders/{id}/accept → status becomes 'partially_fulfilled'
    6. POST /orders/{id}/ship → status becomes 'fulfilled'
    7. GET /merchants/{id}/orders → verify status is now 'fulfilled'
    8. GET /merchants/{id}/attention → verify orders_to_fulfil is now 0
    """
    # 1. Login
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": merchant_setup["owner_email"],
            "password": merchant_setup["owner_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    owner_token = resp.json()["access_token"]
    owner_user = resp.json()["user"]
    assert owner_user["role"] == "merchant_owner"

    headers = {"Authorization": f"Bearer {owner_token}"}

    # 2. Load merchant via by-owner endpoint (what the frontend dashboard does)
    resp = await client.get(
        f"/api/v1/merchants/by-owner/{merchant_setup['owner_id']}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    merchant = resp.json()
    assert merchant["id"] == merchant_setup["merchant_id"]
    assert merchant["kyc_status"] == "verified"

    # 3. Attention counts — one paid order needs fulfilment
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/attention",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["orders_to_fulfil"] == 1

    # 4. List orders — status must be 'paid' so the action column renders buttons
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/orders",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()
    assert len(orders) == 1
    assert orders[0]["status"] == "paid"
    order_id = orders[0]["id"]

    # 5. Accept order (paid -> partially_fulfilled)
    resp = await client.post(
        f"/api/v1/orders/{order_id}/accept",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "partially_fulfilled"

    # 6. Ship order (partially_fulfilled -> fulfilled)
    resp = await client.post(
        f"/api/v1/orders/{order_id}/ship",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "fulfilled"

    # 7. Verify order is fulfilled
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/orders",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    orders = resp.json()
    assert orders[0]["status"] == "fulfilled"

    # 8. Attention count should be 0 (order is now fulfilled)
    resp = await client.get(
        f"/api/v1/merchants/{merchant_setup['merchant_id']}/attention",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["orders_to_fulfil"] == 0


@pytest.mark.asyncio
async def test_merchant_owner_ledger_entries_visible(
    client: AsyncClient,
    db,
    merchant_setup: dict,
    paid_order: dict,
    merchant_owner_token: str,
):
    """A merchant owner's dashboard must surface their ledger entries.

    Regression: ``GET /ledger/entries?merchant_id=...`` scoped the merchant
    branch by ``user_id`` (a User UUID) instead of the real Merchant UUID, so
    ``ledger_entries.merchant_id`` never matched and the Overview page's
    LedgerTable was always empty for merchants.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    merchant_id = merchant_setup["merchant_id"]

    db.add(
        LedgerEntry(
            entry_group_id=uuid4(),
            account_type="merchant_wallet",
            merchant_id=to_uuid(merchant_id),
            order_id=to_uuid(paid_order["order_id"]),
            entry_type="sale",
            direction="credit",
            amount=10000,
            currency="NGN",
        )
    )
    await db.commit()

    resp = await client.get(
        f"/api/v1/ledger/entries?merchant_id={merchant_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    # Before the fix this was `[]` — the merchant_scope matched nothing.
    assert len(entries) >= 1
    assert any(e.get("entry_type") == "sale" for e in entries)


@pytest.mark.asyncio
async def test_ship_records_fulfillment_and_payout_release(
    client: AsyncClient,
    db,
    merchant_setup: dict,
    paid_order: dict,
    merchant_owner_token: str,
):
    """Shipping (completing & delivering) an order must:

    * create a DELIVERED fulfillment so the order detail page's delivery
      section is populated, and
    * record the group-g2 ``payout_release`` ledger entry on delivery
      confirmation (the merchant's held funds move to payout-eligible).

    Regression test: previously ``ship_order`` only flipped ``order.status``
    to ``fulfilled`` and recorded nothing -- so the delivery section was empty
    and no ledger transaction was recorded.
    """
    headers = {"Authorization": f"Bearer {merchant_owner_token}"}
    order_id = paid_order["order_id"]
    merchant_id = merchant_setup["merchant_id"]

    # Sanity: no payout_release exists for this order yet.
    before = (
        (
            await db.execute(
                select(LedgerEntry).where(
                    LedgerEntry.order_id == to_uuid(order_id),
                    LedgerEntry.entry_type == LedgerEntryType.PAYOUT_RELEASE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert before == []

    # Ship == completed & delivered.
    resp = await client.post(f"/api/v1/orders/{order_id}/ship", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "fulfilled"

    # The detail endpoint now surfaces the delivery in the fulfillments list and
    # carries a fulfilled_at timestamp (the "delivery section" used to be empty).
    detail = await client.get(
        f"/api/v1/merchants/{merchant_id}/orders/{order_id}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "fulfilled"
    assert body["fulfilled_at"] is not None
    assert len(body["fulfillments"]) == 1
    ff = body["fulfillments"][0]
    assert ff["status"] == "delivered"
    assert ff["delivered_at"] is not None

    # A payout_release ledger transaction was recorded on delivery confirmation.
    rows = (
        (
            await db.execute(
                select(LedgerEntry).where(
                    LedgerEntry.order_id == to_uuid(order_id),
                    LedgerEntry.merchant_id == to_uuid(merchant_id),
                    LedgerEntry.entry_type == LedgerEntryType.PAYOUT_RELEASE.value,
                    LedgerEntry.direction == LedgerDirection.CREDIT.value,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].account_type == "merchant_wallet"
    assert rows[0].amount == 10000  # single 100.00 NGN minor-unit line item


@pytest.mark.asyncio
async def test_ship_consumes_inventory_reservation_for_tracked_variant(
    client: AsyncClient,
    db,
):
    """Shipping a TRACKED order releases the checkout-time reservation.

    Checkout already hard-reserved tracked stock at order creation
    (``quantity_available -= qty``, ``quantity_reserved += qty`` -- see
    ``app.modules.orders.service``). On fulfillment the sold units leave the
    warehouse, so ``ship_order`` must consume the held reservation
    (``quantity_reserved -= shipped_qty``). It must NOT re-decrement
    ``quantity_available`` -- that would double-count the sale and can violate
    the ``ck_inventory_non_negative`` CHECK constraint.

    Regression: previously ``ship_order`` left ``quantity_reserved``
    permanently inflated, so fulfilling an order never updated inventory.
    """
    plan = CommissionPlan(
        name="default", percentage_bps=1000, flat_fee_minor=0, is_default=True
    )
    db.add(plan)
    await db.flush()

    cat = Category(name="Inventory Test")
    db.add(cat)
    await db.flush()

    owner = User(
        email="inv_owner@example.com",
        password_hash=get_password_hash("InvPass123!"),
        role=UserRole.MERCHANT_OWNER,
        first_name="Inv",
        last_name="Owner",
        gender=Gender.UNSET,
    )
    db.add(owner)
    await db.flush()

    merchant = Merchant(
        owner_user_id=owner.id,
        business_name="Inv Merchant",
        slug="inv-merchant-" + owner.id.hex[:8],
        kyc_status=KycStatus.VERIFIED,
        commission_plan_id=plan.id,
        country="NG",
    )
    db.add(merchant)
    await db.flush()

    store = Store(
        merchant_id=merchant.id,
        name="Inv Store",
        slug="inv-store-" + owner.id.hex[:8],
    )
    db.add(store)
    await db.flush()

    product = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Inv Product",
        slug="inv-product-" + owner.id.hex[:8],
        description="Tracked inventory for the ship-decrement regression test",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.ACTIVE.value,
        base_price_amount=10000,
        base_price_currency="NGN",
    )
    db.add(product)
    await db.flush()

    variant = ProductVariant(
        product_id=product.id,
        sku="INV-SKU-" + owner.id.hex[:8],
        attributes="{}",
        inventory_policy=InventoryPolicy.TRACKED.value,
    )
    db.add(variant)
    await db.flush()

    # Inventory reflecting the post-checkout reservation state for a 2-unit
    # order: the 2 sold units are held as reserved (available already reduced at
    # checkout).
    inventory = Inventory(
        variant_id=variant.id,
        quantity_available=8,
        quantity_reserved=2,
    )
    db.add(inventory)
    await db.flush()

    order = Order(
        buyer_id=owner.id,
        order_number="ORD-INV-" + owner.id.hex[:8],
        status=OrderStatus.PAID.value,
        currency="NGN",
        total_amount=20000,
    )
    db.add(order)
    await db.flush()

    db.add(
        OrderItem(
            order_id=order.id,
            merchant_id=merchant.id,
            product_id=product.id,
            variant_id=variant.id,
            quantity=2,
            unit_price=10000,
            currency="NGN",
            line_total=20000,
        )
    )
    await db.commit()

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": owner.email, "password": "InvPass123!"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Fulfillment trigger: paid -> fulfilled.
    ship = await client.post(f"/api/v1/orders/{order.id}/ship", headers=headers)
    assert ship.status_code == 200, ship.text
    assert ship.json()["status"] == "fulfilled"

    # The checkout reservation is consumed; `available` (already reduced at
    # checkout) is unchanged -- the sale is reflected exactly once.
    inv_after = (
        await db.execute(select(Inventory).where(Inventory.variant_id == variant.id))
    ).scalar_one()
    assert inv_after.quantity_reserved == 0
    assert inv_after.quantity_available == 8
