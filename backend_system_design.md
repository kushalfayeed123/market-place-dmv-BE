# Backend System Design — Marketplace Platform

**Companion to:** `marketplace_system_design.md` (overall architecture)
**Scope:** Backend service design — database schema, auth, rate limiting, idempotency, the immutable ledger, local testing, and free-tier deployment.

---

## 1. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| API framework | **FastAPI** (Python 3.12) | Matches Stoxava/HousePadi conventions; async, typed, OpenAPI for free |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | Explicit schema control needed for the ledger's immutability constraints |
| Database | **PostgreSQL 15+** | JSONB for flexible attributes, row-level security, triggers for ledger immutability |
| Cache / rate limiting / queues | **Redis (Upstash)** | Sliding-window counters, idempotency locks, short-lived job queue |
| Object storage | **Cloudflare R2** (S3-compatible) | Private bucket + signed URLs for digital assets |
| Auth tokens | **JWT (access) + opaque hashed refresh tokens (DB)** | Short-lived access token, revocable refresh sessions |
| Password hashing | **Argon2id** (via `passlib`) | Modern default, memory-hard |
| Background jobs | **Redis Queue (RQ) or Celery-lite / APScheduler** | Payout auto-release, webhook retries, email sends |
| Payment provider | **Paystack**, behind a `PaymentProvider` interface | See main design doc §5.4 |

---

## 2. Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, middleware registration
│   ├── core/
│   │   ├── config.py           # Settings (pydantic-settings), env-driven
│   │   ├── security.py         # password hashing, JWT encode/decode
│   │   ├── rate_limit.py       # Redis sliding-window limiter
│   │   ├── idempotency.py      # idempotency dependency/middleware
│   │   └── logging.py          # JsonFormatter + correlation IDs (Stoxava pattern)
│   ├── db/
│   │   ├── session.py          # engine, sessionmaker
│   │   └── base.py             # declarative base
│   ├── models/                 # SQLAlchemy models (1 file per domain)
│   ├── schemas/                # Pydantic request/response models
│   ├── modules/
│   │   ├── auth/                # register, login, refresh, MFA, password reset
│   │   ├── catalog/              # products, variants, categories
│   │   ├── merchants/            # onboarding, KYC, payout accounts
│   │   ├── orders/                # cart, checkout, order state machine
│   │   ├── payments/               # PaymentProvider impls, webhooks
│   │   ├── ledger/                  # append-only ledger writers + readers
│   │   └── fulfillment/              # shipment + digital delivery workers
│   ├── workers/                 # background jobs (payout release, notifications)
│   └── tests/
├── alembic/
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

Each `modules/*` package only ever writes to the ledger through `ledger/service.py` — no other module is allowed to `INSERT` into `ledger_entries` directly. This is enforced both by code convention and by DB grants (§6.4).

---

## 3. Database Design (PostgreSQL)

### 3.1 Entity overview

```
users ──< merchants ──< stores ──< products ──< product_variants ──< inventory
  │           │                        │
  │           ├──< merchant_payout_accounts        └──< digital_assets
  │           └──< commission_plans (FK)
  │
  ├──< orders ──< order_items
  │       │           │
  │       │           └──> products/variants (FK)
  │       └──< fulfillments
  │
  ├──< refresh_tokens
  └──< audit_log

payment_transactions ──< webhook_events
ledger_entries (append-only; references orders, merchants, payment_transactions)
idempotency_keys (standalone, operational — not part of the financial ledger)
```

### 3.2 Core tables (DDL)

```sql
-- ============ USERS & AUTH ============

CREATE TYPE user_role AS ENUM ('buyer', 'merchant_owner', 'merchant_staff', 'platform_admin');

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           CITEXT UNIQUE NOT NULL,
    phone           TEXT UNIQUE,
    password_hash   TEXT NOT NULL,
    role            user_role NOT NULL DEFAULT 'buyer',
    email_verified_at TIMESTAMPTZ,
    mfa_secret      TEXT,               -- encrypted at rest (envelope encryption)
    mfa_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    status          TEXT NOT NULL DEFAULT 'active', -- active | suspended | deleted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      TEXT NOT NULL,          -- SHA-256 of the opaque token; raw token never stored
    device_info     TEXT,
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    replaced_by     UUID REFERENCES refresh_tokens(id)  -- rotation chain, for reuse detection
);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

-- ============ MERCHANTS ============

CREATE TYPE kyc_status AS ENUM ('pending', 'test_mode', 'verified', 'rejected');

CREATE TABLE commission_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    percentage_bps  INTEGER NOT NULL,   -- basis points, e.g. 1000 = 10.00%
    flat_fee_minor  BIGINT NOT NULL DEFAULT 0,
    currency        CHAR(3) NOT NULL DEFAULT 'NGN',
    is_default      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE merchants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       UUID NOT NULL REFERENCES users(id),
    business_name       TEXT NOT NULL,
    slug                TEXT UNIQUE NOT NULL,
    kyc_status          kyc_status NOT NULL DEFAULT 'pending',
    kyc_provider_ref    TEXT,               -- reference id from identity API
    commission_plan_id  UUID NOT NULL REFERENCES commission_plans(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE merchant_payout_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    provider        TEXT NOT NULL,          -- 'paystack' | 'flutterwave' | 'stripe' ...
    currency        CHAR(3) NOT NULL,
    external_ref    TEXT NOT NULL,          -- e.g. Paystack subaccount_code
    account_last4   TEXT,
    bank_name       TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (merchant_id, provider, currency)
);

CREATE TABLE stores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id     UUID NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    branding        JSONB NOT NULL DEFAULT '{}'
);

-- ============ CATALOG ============

CREATE TYPE fulfillment_kind AS ENUM ('physical', 'digital', 'service');
CREATE TYPE product_status AS ENUM ('draft', 'active', 'suspended');
CREATE TYPE inventory_policy AS ENUM ('tracked', 'untracked', 'unlimited');

CREATE TABLE categories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    parent_id   UUID REFERENCES categories(id)
);

CREATE TABLE product_attribute_schemas (
    category_id UUID PRIMARY KEY REFERENCES categories(id),
    schema      JSONB NOT NULL   -- JSON-Schema-style definition merchants must satisfy
);

CREATE TABLE products (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant_id         UUID NOT NULL REFERENCES merchants(id),
    store_id            UUID NOT NULL REFERENCES stores(id),
    category_id         UUID REFERENCES categories(id),
    title               TEXT NOT NULL,
    slug                TEXT NOT NULL,
    description         TEXT,
    fulfillment_type    fulfillment_kind NOT NULL,
    status              product_status NOT NULL DEFAULT 'draft',
    base_price_amount   BIGINT NOT NULL,      -- minor units (kobo)
    base_price_currency CHAR(3) NOT NULL DEFAULT 'NGN',
    attributes          JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (store_id, slug)
);
CREATE INDEX idx_products_merchant ON products(merchant_id);
CREATE INDEX idx_products_status ON products(status) WHERE status = 'active';

CREATE TABLE product_variants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id          UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    sku                 TEXT UNIQUE NOT NULL,
    attributes          JSONB NOT NULL DEFAULT '{}',   -- {"storage":"128GB","color":"black"} or {"format":"epub"}
    price_override_amount   BIGINT,
    price_override_currency CHAR(3),
    inventory_policy    inventory_policy NOT NULL DEFAULT 'tracked'
);

CREATE TABLE inventory (
    variant_id          UUID PRIMARY KEY REFERENCES product_variants(id) ON DELETE CASCADE,
    quantity_available  INTEGER NOT NULL DEFAULT 0,
    quantity_reserved   INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (quantity_available >= 0 AND quantity_reserved >= 0)
);

CREATE TABLE digital_assets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    variant_id      UUID REFERENCES product_variants(id),
    storage_key     TEXT NOT NULL,      -- private R2/S3 object key, never public
    license_type    TEXT NOT NULL DEFAULT 'n_downloads',
    max_downloads   INTEGER NOT NULL DEFAULT 5,
    expiry_days     INTEGER              -- null = no expiry
);

-- ============ ORDERS & FULFILLMENT ============

CREATE TYPE order_status AS ENUM ('pending', 'paid', 'partially_fulfilled', 'fulfilled', 'cancelled', 'refunded');
CREATE TYPE fulfillment_kind_order AS ENUM ('shipment', 'digital_delivery');
CREATE TYPE fulfillment_status AS ENUM ('pending', 'shipped', 'delivered', 'delivered_digital', 'failed');

CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    buyer_id        UUID NOT NULL REFERENCES users(id),
    status          order_status NOT NULL DEFAULT 'pending',
    currency        CHAR(3) NOT NULL,
    total_amount    BIGINT NOT NULL,   -- minor units
    idempotency_key TEXT UNIQUE,       -- ties order creation to the checkout idempotency key
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    merchant_id     UUID NOT NULL REFERENCES merchants(id),
    product_id      UUID NOT NULL REFERENCES products(id),
    variant_id      UUID REFERENCES product_variants(id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      BIGINT NOT NULL,
    currency        CHAR(3) NOT NULL,
    line_total      BIGINT NOT NULL
);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_merchant ON order_items(merchant_id);

CREATE TABLE fulfillments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    merchant_id         UUID NOT NULL REFERENCES merchants(id),
    type                fulfillment_kind_order NOT NULL,
    status              fulfillment_status NOT NULL DEFAULT 'pending',
    carrier             TEXT,
    tracking_number     TEXT,
    download_token      TEXT,
    downloads_used      INTEGER NOT NULL DEFAULT 0,
    delivered_at        TIMESTAMPTZ,
    dispute_window_ends TIMESTAMPTZ    -- delivered_at + N days, drives payout auto-release
);

-- ============ PAYMENTS ============

CREATE TABLE payment_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES orders(id),
    provider            TEXT NOT NULL,
    provider_reference  TEXT NOT NULL,     -- Paystack transaction reference
    status              TEXT NOT NULL,     -- initialized | success | failed | refunded
    amount              BIGINT NOT NULL,
    currency            CHAR(3) NOT NULL,
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_reference)
);

CREATE TABLE webhook_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        TEXT NOT NULL,
    event_id        TEXT NOT NULL,        -- provider's own event/id or signature hash
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    UNIQUE (provider, event_id)
);

-- ============ IDEMPOTENCY (operational, mutable — NOT part of the ledger) ============

CREATE TABLE idempotency_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT UNIQUE NOT NULL,
    endpoint        TEXT NOT NULL,
    request_hash    TEXT NOT NULL,          -- hash of normalized request body
    status          TEXT NOT NULL DEFAULT 'in_progress', -- in_progress | completed | failed
    response_status INTEGER,
    response_body   JSONB,
    locked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours'
);

-- ============ AUDIT LOG ============

CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id        UUID,
    actor_role      TEXT,
    action          TEXT NOT NULL,
    target_type     TEXT,
    target_id       TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 3.3 The immutable ledger

This is the system of record for every unit of money that moves anywhere in the platform. Three design rules make it trustworthy:

1. **Insert-only.** No `UPDATE`, no `DELETE`, ever — enforced at the database grant level *and* by a trigger, so even a bug or a compromised app credential can't rewrite history.
2. **Double-entry.** Every economic event posts **at least two balanced rows** (a debit and a credit) so `SUM(credit) = SUM(debit)` globally at all times — this is what makes reconciliation mathematically checkable rather than trust-based.
3. **State changes are new rows, not edits.** A payout hold being released is not an `UPDATE` on the original entry — it's a *new* ledger entry that references the original and represents "this amount is now eligible." The current state of any balance is always **derived by summation**, never stored as a mutable field.

```sql
CREATE TYPE ledger_account_type AS ENUM ('platform_revenue', 'merchant_wallet', 'payment_gateway_clearing', 'refund_clearing');
CREATE TYPE ledger_direction AS ENUM ('debit', 'credit');
CREATE TYPE ledger_entry_type AS ENUM ('sale', 'commission', 'payout_hold', 'payout_release', 'payout_paid', 'refund', 'adjustment');

CREATE TABLE ledger_entries (
    id                  BIGSERIAL PRIMARY KEY,               -- monotonic, gapless-enough sequence for audit ordering
    entry_group_id      UUID NOT NULL,                       -- ties together the balanced rows of one economic event
    account_type        ledger_account_type NOT NULL,
    merchant_id         UUID REFERENCES merchants(id),        -- null for pure platform-account rows
    direction           ledger_direction NOT NULL,
    entry_type          ledger_entry_type NOT NULL,
    amount              BIGINT NOT NULL CHECK (amount > 0),   -- minor units; sign comes from `direction`
    currency            CHAR(3) NOT NULL,
    order_id            UUID REFERENCES orders(id),
    payment_transaction_id UUID REFERENCES payment_transactions(id),
    supersedes_entry_id BIGINT REFERENCES ledger_entries(id), -- e.g. payout_release points at the payout_hold it releases
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          TEXT NOT NULL DEFAULT 'system'
);

CREATE INDEX idx_ledger_merchant ON ledger_entries(merchant_id, currency);
CREATE INDEX idx_ledger_order ON ledger_entries(order_id);
CREATE INDEX idx_ledger_group ON ledger_entries(entry_group_id);

-- Immutability enforcement: defense in depth beyond application logic and DB grants
CREATE OR REPLACE FUNCTION prevent_ledger_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'ledger_entries is append-only: % not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ledger_no_update
    BEFORE UPDATE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation();

CREATE TRIGGER trg_ledger_no_delete
    BEFORE DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION prevent_ledger_mutation();

-- Application DB role should not even hold UPDATE/DELETE grants on this table:
-- REVOKE UPDATE, DELETE ON ledger_entries FROM app_role;
-- GRANT INSERT, SELECT ON ledger_entries TO app_role;
```

**Example: a ₦50,000 gadget sale with 10% commission, physical goods (held pending delivery).**

| entry_group_id | account_type | merchant_id | direction | entry_type | amount | note |
|---|---|---|---|---|---|---|
| g1 | payment_gateway_clearing | — | debit | sale | 50,000 | money arrives from Paystack |
| g1 | merchant_wallet | M1 | credit | sale | 50,000 | full sale credited to merchant... |
| g1 | merchant_wallet | M1 | debit | commission | 5,000 | ...then commission is deducted |
| g1 | platform_revenue | — | credit | commission | 5,000 | ...and recognized as platform revenue |
| g1 | merchant_wallet | M1 | debit | payout_hold | 45,000 | net proceeds moved into "held" state |

Later, on delivery confirmation, a **new** balanced pair is posted (not an edit to the row above):

| entry_group_id | account_type | merchant_id | direction | entry_type | amount | supersedes |
|---|---|---|---|---|---|---|
| g2 | merchant_wallet | M1 | credit | payout_release | 45,000 | references the `payout_hold` row |

**Merchant's payout-eligible balance** is simply:

```sql
SELECT
    merchant_id, currency,
    SUM(CASE WHEN direction = 'credit' THEN amount ELSE -amount END) AS balance
FROM ledger_entries
WHERE merchant_id = :merchant_id
  AND entry_type IN ('sale', 'commission', 'payout_release', 'payout_paid', 'refund')
  -- excludes rows still sitting only as `payout_hold` with no matching `payout_release`
GROUP BY merchant_id, currency;
```

In practice this is wrapped in a `merchant_balances` **view** (or materialized view refreshed every few minutes for dashboard performance), never a stored/mutable balance column — the view can always be dropped and rebuilt from raw entries, which is the real test of "immutable ledger drives the system" rather than being decorative.

A **`refund`** simply posts an offsetting pair against the original `entry_group_id`'s order — it never deletes or edits the original sale entry, so the full history of "this order was sold, then refunded" remains visible forever.

### 3.4 Row-Level Security (defense in depth for tenant isolation)

```sql
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
CREATE POLICY merchant_isolation ON products
    USING (merchant_id = current_setting('app.current_merchant_id')::uuid
           OR current_setting('app.current_role') = 'platform_admin');
```
The application sets `app.current_merchant_id`/`app.current_role` per request via `SET LOCAL` inside the transaction, so even a query missing a `WHERE merchant_id = ...` clause cannot cross tenants.

---

## 4. Authentication & Authorization

### 4.1 Flows

- **Registration:** buyers self-register (email + password → verification email). Merchants self-register their `users` row, then complete a separate `merchants` onboarding flow (business info → KYC → payout account) before they can list products.
- **Login:** email + password → Argon2id verify → issue **access token** (JWT, 15 min TTL, claims: `sub`, `role`, `merchant_id?`) + **refresh token** (opaque random 256-bit value, returned as an **httpOnly, Secure, SameSite=Strict cookie**; only its SHA-256 hash is stored in `refresh_tokens`).
- **Refresh rotation:** every use of a refresh token issues a new one and marks the old one `revoked_at` + `replaced_by`. If a **revoked** token is presented again (reuse), treat it as token theft: revoke the entire chain for that user and force re-login.
- **MFA (TOTP):** required for `merchant_owner` and `platform_admin`. Enforced at login for those roles once enabled, and as **step-up verification** (re-prompt even mid-session) before: changing a payout account, changing commission plan, or issuing a manual payout.
- **Password reset:** signed, single-use, short-TTL token emailed to the user; consuming it invalidates all existing refresh tokens for that user.
- **Email verification:** required before a buyer can check out or a merchant can go live.

### 4.2 Authorization (RBAC + ownership)

```python
def require_role(*roles: UserRole):
    def dependency(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(403, "Forbidden")
        return user
    return dependency

def require_merchant_ownership(merchant_id: UUID):
    def dependency(user: User = Depends(get_current_user)):
        if user.role == "platform_admin":
            return user
        if user.role not in ("merchant_owner", "merchant_staff") or user.merchant_id != merchant_id:
            raise HTTPException(403, "Not your store")
        return user
    return dependency
```
Every merchant-scoped route (`/merchants/{merchant_id}/...`) depends on `require_merchant_ownership`, never trusting a `merchant_id` field inside the request body for authorization decisions — only the path param, checked against the authenticated user.

---

## 5. Rate Limiting

Implemented as Redis sliding-window counters (Upstash), applied as **FastAPI middleware + per-route overrides**, layered by scope:

| Scope | Example limit | Key pattern |
|---|---|---|
| Global per-IP | 100 req / min | `rl:ip:{ip}:{minute_bucket}` |
| Per-user, general | 300 req / min | `rl:user:{user_id}:{minute_bucket}` |
| Login attempts | 5 / 5 min per IP+email pair | `rl:login:{ip}:{email_hash}` |
| OTP / password-reset requests | 3 / 15 min per account | `rl:otp:{user_id}` |
| Checkout initiation | 10 / min per user | `rl:checkout:{user_id}` |
| Webhook endpoint | Not rate-limited by count; instead verified by signature + idempotent by event id | — |

```python
async def sliding_window_allow(redis, key: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_seconds)
    pipe.zadd(key, {str(uuid4()): now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds)
    _, _, count, _ = await pipe.execute()
    return count <= limit
```
On rejection: `429 Too Many Requests` with a `Retry-After` header. Auth-sensitive endpoints (login, OTP, password reset) use a **stricter, per-identity** limit specifically to blunt credential-stuffing and brute force, independent of the general per-IP limit.

---

## 6. Idempotency

Required on every **mutating financial** endpoint: `POST /orders/checkout`, `POST /payments/{id}/refund`, `POST /merchants/{id}/payouts`, and internally for webhook processing.

### 6.1 Client-supplied key flow

```
Client sends header: Idempotency-Key: <client-generated UUID>
  │
  ▼
Dependency: look up idempotency_keys WHERE idempotency_key = X
  │
  ├─ Not found ─────────────► INSERT row (status=in_progress, request_hash=hash(body))
  │                            → proceed to handler
  │                            → on success: UPDATE status=completed, store response
  │                            → on failure: UPDATE status=failed (safe to retry)
  │
  ├─ Found, status=completed ─► return the STORED response verbatim (no re-execution)
  │
  ├─ Found, status=in_progress ► return 409 Conflict ("request already processing")
  │
  └─ Found, but request_hash differs ► return 422 (key reused for a different payload — client bug)
```
`idempotency_keys` rows expire after 24h (cleanup job) — long enough to cover realistic client retries, short enough not to bloat the table. This table is **operational**, not financial history, so unlike the ledger it's fine for it to be mutable.

### 6.2 Webhook idempotency

Paystack may deliver the same webhook more than once. `webhook_events (provider, event_id)` has a **unique constraint**; processing does `INSERT ... ON CONFLICT (provider, event_id) DO NOTHING` and only proceeds to post ledger entries if the insert actually happened. Combined with the ledger's `entry_group_id` being deterministic (e.g. derived from the payment transaction id), a duplicate delivery can never double-post revenue.

### 6.3 Idempotency at the ledger boundary specifically

Every ledger-writing operation should be idempotent **on its own terms**, independent of the HTTP-level idempotency key: `ledger_service.post_sale(payment_transaction_id, ...)` first checks whether a `sale` entry already exists for that `payment_transaction_id` before posting — this is the real backstop, since it protects against internal retries (e.g. a worker crash-and-restart) as well as external duplicate webhooks.

### 6.4 Database grants recap

```sql
-- App runtime role: can insert/select the ledger, never mutate it
REVOKE UPDATE, DELETE ON ledger_entries FROM app_role;
GRANT INSERT, SELECT ON ledger_entries TO app_role;
GRANT USAGE, SELECT ON SEQUENCE ledger_entries_id_seq TO app_role;

-- idempotency_keys is operational and CAN be updated by the app
GRANT SELECT, INSERT, UPDATE ON idempotency_keys TO app_role;
```

---

## 7. Testing Locally

### 7.1 Docker Compose

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: marketplace
      POSTGRES_USER: marketplace
      POSTGRES_PASSWORD: localdev
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  redis:
    image: redis:7
    ports: ["6379:6379"]

  api:
    build: .
    env_file: .env
    depends_on: [db, redis]
    ports: ["8000:8000"]
    command: uvicorn app.main:app --reload --host 0.0.0.0

volumes:
  pgdata:
```

### 7.2 Environment

```
# .env.example
DATABASE_URL=postgresql+asyncpg://marketplace:localdev@localhost:5432/marketplace
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=change-me
PAYSTACK_SECRET_KEY=sk_test_xxx        # Paystack TEST mode key
PAYSTACK_PUBLIC_KEY=pk_test_xxx
KYC_ENFORCEMENT_ENABLED=false          # off locally per earlier decision
R2_BUCKET=marketplace-dev
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

### 7.3 Migrations & seed data

```bash
alembic upgrade head
python -m app.scripts.seed_demo   # creates the gadget vendor + author test merchants, sample products
```

### 7.4 Test suite layout

- **Unit tests** — pure logic: commission calculation, ledger balance derivation, idempotency-key hashing. No DB.
- **Integration tests** — real Postgres (a disposable test DB, created/dropped per test session; each test runs inside a transaction that's rolled back, via `pytest` fixtures + `SQLAlchemy` nested transactions) + real Redis (`fakeredis` or a throwaway Redis container).
- **Payment provider tests** — the `PaymentProvider` interface (§5.4 of the main design doc) means tests inject a `FakePaymentProvider` that returns deterministic success/failure without hitting the network, for fast unit/integration coverage. Separately, a **small number of slow-marked tests** run against Paystack's real sandbox using `sk_test_...` keys and Paystack's documented test card numbers, to catch real integration drift.
- **Webhook simulation:** since Paystack can't reach `localhost` directly, either (a) use `ngrok`/Cloudflare Tunnel to expose the local server and register that URL in the Paystack test dashboard, or (b) construct a signed test payload locally and POST it directly:

```python
import hmac, hashlib, json, httpx

payload = {"event": "charge.success", "data": {"reference": "test_ref_123", ...}}
body = json.dumps(payload).encode()
signature = hmac.new(TEST_SECRET.encode(), body, hashlib.sha512).hexdigest()

httpx.post("http://localhost:8000/webhooks/paystack",
           content=body,
           headers={"x-paystack-signature": signature})
```
This is the fastest way to exercise the full webhook → ledger → fulfillment path without any network dependency.

- **Ledger-specific tests** are worth calling out as their own suite: assert that (a) `UPDATE`/`DELETE` against `ledger_entries` always raises, (b) every posted `entry_group_id` balances to zero across debits/credits, (c) replaying the same webhook twice never changes the computed merchant balance.

---

## 8. Deploying on Free Servers

| Component | Free-tier choice | Notes |
|---|---|---|
| API (FastAPI) | **Render** free Web Service | Spins down after ~15 min idle → cold start on next request (acceptable for MVP/demo; mention to stakeholders). No persistent disk — fine, since all assets live in R2 and state lives in Postgres/Redis. |
| Database | **Neon** (or Supabase) free Postgres | Prefer over Render's free Postgres, which **expires after 90 days**. Neon's free tier is a persistent, always-available serverless Postgres — a better fit for anything beyond a demo. |
| Redis | **Upstash** free tier | Already your standard choice; REST-based, works fine from Render. |
| Object storage | **Cloudflare R2** free tier | 10GB storage / 1M Class A ops free — plenty for early digital assets + product images. |
| Frontend | **Vercel** free tier | See frontend design doc. |

### 8.1 Deployment steps (Render)

1. Push repo to GitHub.
2. Render → New Web Service → connect repo → set build command (`pip install -r requirements.txt`) and start command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
3. Add environment variables in Render's dashboard (never commit `.env`) — `DATABASE_URL` (from Neon), `REDIS_URL` (from Upstash), `PAYSTACK_SECRET_KEY` (test key initially), `JWT_SECRET`, `R2_*`.
4. Add a **Render "Release Command"**: `alembic upgrade head` — runs migrations automatically on every deploy.
5. Point Paystack's webhook URL (test mode) at `https://<your-render-app>.onrender.com/webhooks/paystack`.

### 8.2 CI (GitHub Actions)

```yaml
name: ci
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env: { POSTGRES_PASSWORD: test }
        ports: ["5432:5432"]
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: alembic upgrade head
      - run: pytest -v
```
Render auto-deploys on push to `main` once CI is green — no separate CD tooling needed at this scale.

### 8.3 Free-tier limitations to plan around

- **Cold starts** on Render free web services (~30–50s wake-up) — acceptable for a demo/early-traction phase; upgrading to a paid instance ($7/mo tier) removes this the moment real buyers show up.
- **Neon free tier** has compute auto-suspend on inactivity too (wakes on first query, sub-second) — fine for Postgres since it doesn't need to "serve" requests directly.
- **No cron on Render free tier** for the payout auto-release job — run it as a scheduled **GitHub Actions workflow** (`schedule: cron`) that calls a protected internal endpoint, or use Upstash's built-in QStash scheduler (also has a free tier) instead of relying on the web dyno's own clock.

---

## 9. API Surface (representative, not exhaustive)

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/auth/register` | none | rate-limited |
| POST | `/auth/login` | none | rate-limited, MFA challenge if enabled |
| POST | `/auth/refresh` | refresh cookie | rotates token |
| POST | `/merchants/{id}/products` | merchant_owner (ownership) | |
| GET | `/catalog/products` | none | public browse |
| POST | `/orders/checkout` | buyer | **requires Idempotency-Key** |
| POST | `/webhooks/paystack` | signature | idempotent by event id |
| POST | `/payments/{id}/refund` | platform_admin | **requires Idempotency-Key** |
| GET | `/merchants/{id}/ledger` | merchant_owner (ownership) | read-only, derived balance view |
| POST | `/merchants/{id}/payouts` | platform_admin | **requires Idempotency-Key**, triggers `payout_paid` entries |
