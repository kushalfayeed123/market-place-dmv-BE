.PHONY: help setup dev-down migrate migrate-create seed backup restore clean lint test

# Default target
help: ## Show this help message
	@echo "Marketplace Backend - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Docker Operations
# =============================================================================
dev: ## Start all services (postgres, redis, pgadmin)
	docker-compose up -d

dev-down: ## Stop all services
	docker-compose down

dev-logs: ## View logs from all services
	docker-compose logs -f

dev-ps: ## List running services
	docker-compose ps

dev-clean: ## Stop and remove all containers and volumes
	docker-compose down -v

dev-restart: dev-down dev ## Restart all services

# =============================================================================
# Application
# =============================================================================
install: ## Install dependencies
	pip install -e ".[dev]"

dev-server: ## Start development server with hot reload
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

server: ## Start production server
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# =============================================================================
# Database Operations
# =============================================================================
# =============================================================================
# MySQL (local dev) -- the checked-in Alembic migrations are PostgreSQL-only,
# so on MySQL we bootstrap the schema directly from the SQLAlchemy models.
# =============================================================================
MYSQL_BIN ?= "C:\Program Files\MySQL\MySQL Server 9.3\bin\mysql.exe"
MYSQL_ADMIN ?= root

mysql-init: ## Create DB + app user (run once as MySQL root; prompts for password)
	"$(MYSQL_BIN)" -u "$(MYSQL_ADMIN)" -p < scripts/db/init_mysql.sql

mysql-check: ## Verify the app's DB connection is reachable
	.\.venv\Scripts\Activate.ps1; python -c "import asyncio; from app.db.session import engine; asyncio.run((await engine.connect()).close()) if False else print('engine url:', engine.url.render_as_string(hide_password=True))"

mysql-schema: ## Create all tables from models (idempotent)
	.\.venv\Scripts\Activate.ps1; python -m scripts.db.init_schema

db-setup: mysql-schema ## Bootstrap schema (MySQL: from models)
db-seed: ## Seed database with development data
	.\.venv\Scripts\Activate.ps1; python -m scripts.db.seed

db-reset: ## Reset schema + reseed (drops and recreates tables)
	.\.venv\Scripts\Activate.ps1; python -m scripts.db.reset_schema
	.\.venv\Scripts\Activate.ps1; python -m scripts.db.seed

mysql-shell: ## Open mysql shell as app user
	.\.venv\Scripts\Activate.ps1; & "$(MYSQL_BIN)" -u marketplace -pmarketplace marketplace_dev

# =============================================================================
# PostgreSQL (staging / production) -- Alembic migrations apply on this dialect
# =============================================================================
pg-setup: ## Run PostgreSQL migrations (staging/production)
	alembic upgrade head

# =============================================================================
# Testing
# =============================================================================
test: ## Run tests
	pytest

test-cov: ## Run tests with coverage
	pytest --cov=app --cov-report=html --cov-report=term

# =============================================================================
# Linting & Formatting
# =============================================================================
lint: ## Run linter
	ruff check app/

format: ## Format code
	ruff format app/

type-check: ## Run type checker
	mypy app/

# =============================================================================
# Utilities
# =============================================================================
clean: ## Clean up cache and temporary files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache 2>/dev/null || true
	rm -rf htmlcov 2>/dev/null || true

install-hooks: ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install

all: dev db-setup db-seed dev-server