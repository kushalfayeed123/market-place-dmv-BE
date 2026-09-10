# Marketplace Backend

This is the backend service for the Marketplace Platform, built with FastAPI and following the system design specifications.

## Features

- **Authentication & Authorization**: JWT-based auth with refresh tokens, MFA, role-based access control
- **Financial Ledger**: Immutable, append-only ledger with double-entry accounting
- **Idempotency**: Client-supplied idempotency keys for financial operations
- **Rate Limiting**: Sliding window counters using Redis
- **Modular Architecture**: Organized by business domain (auth, catalog, orders, payments, etc.)
- **Database**: PostgreSQL with SQLAlchemy ORM and Alembic migrations
- **Caching**: Redis for rate limiting and idempotency keys
- **Storage**: Cloudflare R2 for digital assets
- **Payments**: Paystack integration with webhook handling
- **Background Workers**: Payout auto-release, webhook processing

## Technology Stack

- **Framework**: FastAPI (Python 3.12)
- **ORM**: SQLAlchemy 2.0 + Alembic
- **Database**: PostgreSQL 15+
- **Cache/Queue**: Redis (Upstash)
- **Object Storage**: Cloudflare R2 (S3-compatible)
- **Authentication**: JWT + opaque refresh tokens
- **Password Hashing**: Argon2id
- **Background Jobs**: Redis Queue or similar

## Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app entry point
│   ├── core/
│   │   ├── config.py           # Settings management
│   │   ├── security.py         # Password hashing, JWT handling
│   │   ├── rate_limit.py       # Redis sliding-window limiter
│   │   ├── idempotency.py      # Idempotency dependency/middleware
│   │   └── logging.py          # JSON formatting with correlation IDs
│   ├── db/
│   │   ├── session.py          # Database session management
│   │   └── base.py             # Declarative base for models
│   ├── models/                 # SQLAlchemy models
│   ├── schemas/                # Pydantic request/response models
│   ├── modules/                # Business domain modules
│   │   ├── auth/               # Authentication and authorization
│   │   ├── catalog/            # Products, categories, inventory
│   │   ├── merchants/          # Merchant onboarding and management
│   │   ├── orders/             # Cart, checkout, order management
│   │   ├── payments/           # Payment processing and webhooks
│   │   ├── ledger/             # Immutable financial ledger
│   │   └── fulfillment/        # Shipments and digital delivery
│   ├── workers/                # Background job processors
│   └── tests/                  # Test suite
├── alembic/                    # Database migration scripts
├── docker-compose.yml          # Local development environment
├── Dockerfile                  # Containerization
├── pyproject.toml              # Project dependencies and metadata
└── .env.example                # Environment variable template
```

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- Redis 7+
- Docker and Docker Compose (optional, for local development)

### Local Development (Docker)

The fastest way to get started is using Docker for the database and Redis:

1. **Clone the repository** and navigate to the backend directory

2. **Start services** (PostgreSQL, Redis, pgAdmin):
   ```bash
   make dev
   ```

3. **Set up environment variables**:
   ```bash
   cp .env.local.example .env
   # Edit .env with your local development values (or use defaults)
   ```

4. **Install dependencies**:
   ```bash
   make install
   ```

5. **Run database migrations**:
   ```bash
   make db-setup
   ```

6. **Seed the database** with test data:
   ```bash
   make db-seed
   ```

7. **Start the development server**:
   ```bash
   make dev-server
   ```

8. **View API documentation**:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

#### Available Services

| Service | URL | Credentials |
|---------|-----|-------------|
| API | http://localhost:8000 | - |
| API Docs (Swagger) | http://localhost:8000/docs | - |
| API Docs (ReDoc) | http://localhost:8000/redoc | - |
| PostgreSQL | localhost:5432 | marketplace:marketplace |
| Redis | localhost:6379 | redis:redis |
| pgAdmin | http://localhost:5050 | admin@marketplace.local:admin |

#### Default Users (after seeding)

| Email | Password | Role |
|-------|----------|------|
| admin@marketplace.local | admin123 | Platform Admin |
| buyer@marketplace.local | buyer123 | Buyer |
| merchant@marketplace.local | merchant123 | Merchant Owner |

### Local Development (Manual Setup)

1. **Clone the repository** and navigate to the backend directory

2. **Install dependencies** (using uv):
   ```bash
   # If you don't have uv installed, install it first:
   # curl -LsSf https://astral.sh/uv/install.sh | sh
   # Or: pipx install uv
   
   uv pip install -e .
   ```

3. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your local development values
   ```

4. **Start the services**:
   ```bash
   docker-compose up -d
   ```
   This will start PostgreSQL and Redis containers.

5. **Run database migrations**:
   ```bash
   alembic upgrade head
   ```

6. **Start the API server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

7. **Access the API documentation**:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc

### Commands Reference

Use the Makefile for common operations:

```bash
# Docker
make dev              # Start PostgreSQL, Redis, pgAdmin
make dev-down         # Stop services
make dev-logs         # View service logs
make dev-ps           # List running services
make dev-clean        # Stop and remove containers, volumes, networks

# App
make install          # Install dependencies
make dev-server       # Start dev server with hot reload
make server           # Start production server

# Database
make db-setup         # Run migrations
make db-migrate       # Apply pending migrations
make db-migrate-create MSG="description"  # Create new migration
make db-migrate-rollback  # Rollback one migration
make db-migrate-history   # Show migration history
make db-migrate-current   # Show current migration
make db-seed          # Seed test data
make db-reset         # Complete database reset (clean + migrate + seed)
make db-shell         # Open psql shell in container

# Backup/Restore
make db-backup        # Create timestamped backup
make db-restore FILE=backups/backup_file.sql.gz  # Restore from backup

# Testing & Quality
make test             # Run tests
make test-cov         # Run tests with coverage
make lint             # Run linter
make format           # Format code
```

### Environment Configuration

Copy the example file and customize:
```bash
cp .env.local.example .env
```

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | - |
| `REDIS_URL` | Redis connection string | - |
| `ENVIRONMENT` | Environment name | development |
| `DEBUG` | Enable debug mode | true |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT expiration (minutes) | 60 |

### Running Tests

```bash
# Run all tests
make test

# Run tests with coverage
make test-cov

# Run specific test file
pytest app/tests/test_auth.py
```

### Deployment

The backend is designed to be deployed on free-tier services for MVP/demo:

- **API**: Render free Web Service
- **Database**: Neon free Postgres (preferred over Render's free Postgres)
- **Redis**: Upstash free tier
- **Object Storage**: Cloudflare R2 free tier
- **Frontend**: Vercel free tier

See the system design document for detailed deployment instructions.

## API Endpoints

See the automatically generated API documentation at `/docs` or `/redoc` for complete endpoint details.

### Authentication
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login with email/password
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/mfa/setup` - Setup MFA
- `POST /api/v1/auth/mfa/verify` - Verify MFA token
- `POST /api/v1/auth/password-reset/request` - Request password reset

### Catalog
- `POST /api/v1/catalog/categories` - Create category
- `GET /api/v1/catalog/categories` - List categories
- `POST /api/v1/catalog/products` - Create product
- `GET /api/v1/catalog/products` - List products
- `POST /api/v1/catalog/products/{product_id}/variants` - Create product variant
- `PUT /api/v1/catalog/inventory/{variant_id}` - Update inventory

### Orders
- `POST /api/v1/orders/checkout` - Create order (requires idempotency key)
- `GET /api/v1/orders/{order_id}` - Get order details
- `GET /api/v1/orders/` - List user's orders

### Payments
- `POST /api/v1/payments/process` - Process payment (requires idempotency key)
- `POST /api/v1/payments/{payment_id}/refund` - Refund payment (requires idempotency key, platform admin)
- `POST /api/v1/payments/webhooks/paystack` - Paystack webhook endpoint

### Ledger
- `GET /api/v1/ledger/entries` - List ledger entries (with filtering)
- `GET /api/v1/ledger/balance/{merchant_id}` - Get merchant balance

### Fulfillment
- `POST /api/v1/fulfillment/` - Create fulfillment
- `PUT /api/v1/fulfillment/{fulfillment_id}/shipment` - Update shipment
- `PUT /api/v1/fulfillment/{fulfillment_id}/digital-delivery` - Update digital delivery
- `GET /api/v1/fulfillment/{fulfillment_id}` - Get fulfillment details
- `GET /api/v1/fulfillment/order/{order_id}` - List fulfillments for order

## Design Highlights

### Immutable Ledger
The financial ledger is append-only with double-entry accounting. Every economic event creates at least two balanced ledger entries (debit and credit). Balance is calculated by summing entries, never stored as a mutable field.

### Idempotency
All mutating financial endpoints require an `Idempotency-Key` header. The system ensures that duplicate requests with the same key return the same response without side effects.

### Rate Limiting
Implemented using Redis sliding window counters with different limits for:
- Global per-IP
- Per-user
- Login attempts
- OTP/password reset requests
- Checkout initiation

### Security
- Passwords hashed with Argon2id
- Access tokens are short-lived JWTs (15 min)
- Refresh tokens are opaque, hashed values stored in database
- MFA required for sensitive operations
- Row-level security for tenant isolation
- Principle of least privilege database permissions

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Install dev dependencies (optional, for testing/linting):
   ```bash
   uv pip install -e .[dev]
   ```
6. Ensure all tests pass
7. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.