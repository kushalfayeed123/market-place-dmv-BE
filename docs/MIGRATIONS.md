# Database Migrations (Alembic)

How to bring any environment's database — including the Aiven-hosted production
MySQL instance — up to the latest schema without affecting existing data.

## Layout

- Config: [alembic.ini](alembic.ini) (`script_location = alembic`)
- Env bootstrap: [alembic/env.py](alembic/env.py) — reads `DATABASE_URL` from the
  environment (or `.env`) and points Alembic at it. No URL is hardcoded in
  `alembic.ini`.
- Migration scripts: [alembic/versions/](alembic/versions/)
- Models (autogenerate source of truth): [app/models/](app/models/)

## Migration chain (single linear branch)

```
04c9b47b55f2  initial schema (index tweak)
750efb429e88  initial schema
156cf21ef8a1  users: first_name / last_name
541724af8568  support_tickets + knowledge_documents
9457672225d3  products: image urls
c7f3a1b2d4e5  notifications + orders.order_number
d8f2a5b1c9e3  disputes + conversations
e5f6a7b8c9d0  payouts table
a1b2c3d4e5f6  users: password reset
e1b27b0f76d4  users: password_reset_token_hash
f2c3d4e5f6a7  payment_transactions: payment_url
7a3b1c9d2e4f  orders: delivery_address
b2c3d4e5f6a7  documents table + KYC
f4e5d6c7b8a9  product_product_types (backfills from products.fulfillment_type)
c9d8e7f6a5b4  digital_assets table          <-- head
```

Run `alembic heads` to confirm the head is `c9d8e7f6a5b4`.

## Production connection (Aiven MySQL)

Prod instance details:

| Setting  | Value                                                        |
|----------|--------------------------------------------------------------|
| Host     | `mysql-1f8227c1-segunajanaku617-1622.b.aivencloud.com`       |
| Port     | `28456`                                                      |
| User     | `avnadmin`                                                   |
| Database | `markto`                                                     |
| TLS      | required — download the CA certificate from the Aiven console (Service → Overview → CA certificate) |

**Never commit the password.** Export the URL as an environment variable instead
of editing `.env`:

```powershell
cd C:\sandbox\market-place\backend
.\.venv\Scripts\Activate.ps1
$env:DATABASE_URL = "mysql+asyncmy://avnadmin:<PASSWORD>@mysql-1f8227c1-segunajanaku617-1622.b.aivencloud.com:28456/markto"
```

Because Aiven requires TLS, pass the CA cert in [alembic/env.py](alembic/env.py)
inside `run_async_migrations()`:

```python
connectable = async_engine_from_config(
    config.get_section(config.config_ini_section, {}),
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,
    connect_args={"ssl": {"ca": r"C:\path\to\aiven-ca.pem"}},
)
```

## Migration procedure (runbook)

1. **Back up first.** Either use Aiven's backup / point-in-time recovery in the
   console, or:

   ```powershell
   mysqldump -h mysql-1f8227c1-segunajanaku617-1622.b.aivencloud.com -P 28456 `
     -u avnadmin -p --ssl-mode=REQUIRED --single-transaction --routines --triggers `
     markto > markto-backup-$(Get-Date -Format yyyyMMdd-HHmmss).sql
   ```

2. **Check current state:**

   ```powershell
   alembic current    # revision recorded in the alembic_version table
   alembic heads      # expected: c9d8e7f6a5b4
   alembic history    # full chain
   ```

3. **Preview the SQL** (offline — connects only to render SQL, writes nothing;
   replace `<current>` with the revision from step 2):

   ```powershell
   alembic upgrade <current>:head --sql
   ```

4. **Apply:**

   ```powershell
   alembic upgrade head
   ```

5. **Verify:**

   ```powershell
   alembic current    # must print c9d8e7f6a5b4
   ```

   Then in MySQL run `SHOW TABLES;` and confirm the new tables exist
   (`payouts`, `disputes`, `conversations`, `documents`, `digital_assets`,
   `product_product_types`, `notifications`, `support_tickets`,
   `knowledge_documents`) and new columns exist (`users.first_name`,
   `users.last_name`, `orders.delivery_address`, `orders.order_number`,
   `payment_transactions.payment_url`, …).

## Data safety

- All migrations are **additive** (new tables/columns, index changes). None drop
  tables or columns, so existing data is preserved.
- The only migration that writes to existing rows is `f4e5d6c7b8a9`, which
  backfills `product_product_types` from `products.fulfillment_type`
  (`INSERT ... SELECT`), keeping current listings in their original section.
- Several migrations are idempotent (they check `inspector.get_table_names()`
  before creating tables), so re-running is safe.

## Rollback

Every migration implements `downgrade()`:

```powershell
alembic downgrade -1          # undo last migration
alembic downgrade <revision>  # downgrade to a specific revision
```

Prefer restoring the backup from step 1 for production rollbacks.

## Generating new migrations

```powershell
# make model changes in app/models/, then:
alembic revision --autogenerate -m "short description"
# review the generated file in alembic/versions/ before running
alembic upgrade head
```
