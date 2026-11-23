"""End-to-end tests for merchant share links (store-wide and product-set links)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from uuid import uuid4

from app.core.security import get_password_hash, to_uuid
from app.models.category import Category
from app.models.commission_plan import CommissionPlan
from app.models.enums import InventoryPolicy
from app.models.inventory import Inventory
from app.models.merchant import KycStatus, Merchant
from app.models.product import FulfillmentKind, Product, ProductStatus
from app.models.product_variant import ProductVariant
from app.models.store import Store
from app.models.user import Gender, User, UserRole


@pytest.fixture
async def link_setup(db) -> dict:
    """Create a merchant, store, and a couple of active products for link testing."""
    plan = CommissionPlan(
        name="default", percentage_bps=1000, flat_fee_minor=0, is_default=True
    )
    db.add(plan)
    await db.flush()

    cat = Category(name="Electronics")
    db.add(cat)
    await db.flush()

    owner = User(
        email="link_owner@example.com",
        password_hash=get_password_hash("LinkPass123!"),
        role=UserRole.MERCHANT_OWNER,
        first_name="Link",
        last_name="Owner",
        gender=Gender.UNSET,
    )
    db.add(owner)
    await db.flush()

    merchant = Merchant(
        owner_user_id=owner.id,
        business_name="Link Test Merchant",
        slug="link-test-merchant-" + owner.id.hex[:8],
        kyc_status=KycStatus.VERIFIED,
        commission_plan_id=plan.id,
        country="NG",
    )
    db.add(merchant)
    await db.flush()

    store = Store(
        merchant_id=merchant.id,
        name="Link Test Store",
        slug="link-test-store-" + owner.id.hex[:8],
    )
    db.add(store)
    await db.flush()

    # Create 2 active products and 1 inactive
    p1 = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Link Product 1",
        slug="link-prod-1-" + owner.id.hex[:8],
        description="First link product",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.ACTIVE.value,
        base_price_amount=5000,  # ₦50.00
        base_price_currency="NGN",
    )
    db.add(p1)
    await db.flush()

    v1 = ProductVariant(
        product_id=p1.id,
        sku="LINK-PROD1-SKU",
        attributes="{}",
        inventory_policy=InventoryPolicy.TRACKED.value,
    )
    db.add(v1)
    await db.flush()

    inv1 = Inventory(variant_id=v1.id, quantity_available=10, quantity_reserved=0)
    db.add(inv1)

    p2 = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Link Product 2",
        slug="link-prod-2-" + owner.id.hex[:8],
        description="Second link product",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.ACTIVE.value,
        base_price_amount=10000,  # ₦100.00
        base_price_currency="NGN",
    )
    db.add(p2)
    await db.flush()

    v2 = ProductVariant(
        product_id=p2.id,
        sku="LINK-PROD2-SKU",
        attributes="{}",
        inventory_policy=InventoryPolicy.TRACKED.value,
    )
    db.add(v2)
    await db.flush()

    inv2 = Inventory(variant_id=v2.id, quantity_available=5, quantity_reserved=0)
    db.add(inv2)

    p3 = Product(
        merchant_id=merchant.id,
        store_id=store.id,
        category_id=cat.id,
        title="Inactive Product",
        slug="link-prod-3-" + owner.id.hex[:8],
        description="Should not appear in links",
        fulfillment_type=FulfillmentKind.PHYSICAL.value,
        status=ProductStatus.SUSPENDED.value,
        base_price_amount=7500,
        base_price_currency="NGN",
    )
    db.add(p3)
    await db.flush()

    await db.commit()

    return {
        "owner_id": str(owner.id),
        "owner_password": "LinkPass123!",
        "merchant_id": str(merchant.id),
        "store_id": str(store.id),
        "variant_id_1": str(v1.id),
        "variant_id_2": str(v2.id),
        "product_id_1": str(p1.id),
        "product_id_2": str(p2.id),
    }


@pytest.fixture
async def merchant_owner_token(client: AsyncClient, link_setup: dict) -> str:
    """Log in as the merchant owner and return the bearer token."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "link_owner@example.com",
            "password": link_setup["owner_password"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


class TestCreateStoreLink:
    """Test creating a store-wide share link."""

    async def test_create_store_link(self, client: AsyncClient, merchant_owner_token: str, link_setup: dict):
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "title": "My Store Link"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["code"]
        assert data["title"] == "My Store Link"
        assert data["url"].endswith(f"/s/{data['code']}")
        assert data["is_active"] == "active"
        assert data["product_ids"] == []  # store link embeds no specific products

    async def test_create_product_set_link(self, client: AsyncClient, merchant_owner_token: str, link_setup: dict):
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        resp = await client.post(
            "/api/v1/links/",
            json={
                "store_id": link_setup["store_id"],
                "product_ids": [link_setup["product_id_1"], link_setup["product_id_2"]],
                "title": "My Product Set Link",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["title"] == "My Product Set Link"
        assert data["url"].endswith(f"/s/{data['code']}")
        assert len(data["product_ids"]) == 2
        assert link_setup["product_id_1"] in data["product_ids"]
        assert link_setup["product_id_2"] in data["product_ids"]


class TestListLinks:
    """Test listing a merchant's links."""

    async def test_list_links_empty(self, client: AsyncClient, merchant_owner_token: str):
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        resp = await client.get("/api/v1/links/", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    async def test_list_links_with_entries(self, client: AsyncClient, merchant_owner_token: str, link_setup: dict):
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        # Create one link first so the list is non-empty.
        create_resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "title": "Listed Link"},
            headers=headers,
        )
        assert create_resp.status_code == 201, create_resp.text
        resp = await client.get("/api/v1/links/", headers=headers)
        data = resp.json()
        assert len(data) >= 1
        assert any(l["title"] == "Listed Link" for l in data)


class TestResolveStoreLink:
    """Test public resolution of share links."""

    async def test_resolve_store_link(self, client: AsyncClient, link_setup: dict):
        # First create a store link
        owner_token_resp = await client.post(
            "/api/v1/auth/login",
            data={
                "username": "link_owner@example.com",
                "password": "LinkPass123!",
            },
        )
        owner_token = owner_token_resp.json()["access_token"]

        # Create a store link
        create_resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "title": "Store Link"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert create_resp.status_code == 201
        code = create_resp.json()["code"]

        # Resolve it publicly (no auth)
        resp = await client.get(f"/api/v1/links/public/{code}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["kind"] == "store"
        assert data["title"] == "Store Link"
        assert data["url"].endswith(f"/s/{code}")
        assert data["store"]["name"] == "Link Test Merchant"
        # Should list active products (p1 and p2, not p3 which is suspended)
        product_titles = [p["title"] for p in data["products"]]
        assert "Link Product 1" in product_titles
        assert "Link Product 2" in product_titles
        assert "Inactive Product" not in product_titles

    async def test_resolve_product_set_link(self, client: AsyncClient, link_setup: dict):
        owner_token_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "link_owner@example.com", "password": "LinkPass123!"},
        )
        owner_token = owner_token_resp.json()["access_token"]

        create_resp = await client.post(
            "/api/v1/links/",
            json={
                "store_id": link_setup["store_id"],
                "product_ids": [link_setup["product_id_1"], link_setup["product_id_2"]],
                "title": "Product Set Link",
            },
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert create_resp.status_code == 201
        code = create_resp.json()["code"]

        # Resolve publicly
        resp = await client.get(f"/api/v1/links/public/{code}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["kind"] == "products"
        assert data["title"] == "Product Set Link"
        product_titles = [p["title"] for p in data["products"]]
        assert "Link Product 1" in product_titles
        assert "Link Product 2" in product_titles
        assert len(data["products"]) == 2
        # Each resolved product carries enough to render a card + purchase flow
        for p in data["products"]:
            assert p["id"]
            assert p["base_price_amount"] > 0
            assert p["base_price_currency"] == "NGN"
            assert p["variants"], "resolved products must include variants for add-to-cart"


class TestDeactivateLink:
    """Test deactivating a share link."""

    async def test_deactivate_link(self, client: AsyncClient, merchant_owner_token: str, link_setup: dict):
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        # Create a link
        create_resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "title": "To Be Deactivated"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        code = create_resp.json()["code"]
        link_id = create_resp.json()["id"]

        # Deactivate it
        deact_resp = await client.post(
            f"/api/v1/links/{link_id}/deactivate",
            headers=headers,
        )
        assert deact_resp.status_code == 200, deact_resp.text
        data = deact_resp.json()
        assert data["is_active"] == "inactive"

        # Verify it no longer resolves
        resp = await client.get(f"/api/v1/links/public/{code}")
        assert resp.status_code == 404, resp.text

    async def test_create_link_unauthenticated(self, client: AsyncClient, link_setup: dict):
        # No auth header at all -> 401
        create_resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "title": "No Auth"},
        )
        assert create_resp.status_code in (401, 403), create_resp.text

    async def test_create_link_rejects_foreign_products(
        self, client: AsyncClient, merchant_owner_token: str, link_setup: dict, db
    ):
        """A merchant cannot embed another merchant's product in their link."""
        headers = {"Authorization": f"Bearer {merchant_owner_token}"}
        resp = await client.post(
            "/api/v1/links/",
            json={"store_id": link_setup["store_id"], "product_ids": [str(uuid4())]},
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    async def test_resolve_unknown_code_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/links/public/doesnotexist123")
        assert resp.status_code == 404, resp.text