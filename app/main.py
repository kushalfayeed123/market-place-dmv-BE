# app/main.py
"""
Main FastAPI application entry point.
Initializes the app, registers middleware, and includes routers.
"""

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import setup_rate_limiting
from app.core.security import setup_security
from app.modules.auth.router import router as auth_router
from app.modules.catalog.router import router as catalog_router
from app.modules.commissions.router import router as commissions_router
from app.modules.fulfillment.router import router as fulfillment_router
from app.modules.ledger.router import router as ledger_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.support.router import router as support_router
from app.modules.merchants.router import router as merchants_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router
from app.modules.product_attributes.router import router as product_attributes_router
from app.modules.stores.router import router as stores_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Setup logging
setup_logging()

# Create FastAPI app
app = FastAPI(
    title="Marketplace API",
    description="Backend API for the Marketplace Platform",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if settings.API_V1_STR else None,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Setup CORS
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Setup rate limiting
setup_rate_limiting(app)

# Initialize Redis connection for rate limiting
from app.core.rate_limit import init_redis

# Store the init function to be called during startup
redis_init_func = init_redis

# Include routers
app.include_router(auth_router, prefix=f"{settings.API_V1_STR}/auth", tags=["auth"])
app.include_router(catalog_router, prefix=f"{settings.API_V1_STR}/catalog", tags=["catalog"])
app.include_router(commissions_router, prefix=f"{settings.API_V1_STR}/commissions", tags=["commissions"])
app.include_router(merchants_router, prefix=f"{settings.API_V1_STR}/merchants", tags=["merchants"])
app.include_router(stores_router, prefix=f"{settings.API_V1_STR}/stores", tags=["stores"])
app.include_router(orders_router, prefix=f"{settings.API_V1_STR}/orders", tags=["orders"])
app.include_router(payments_router, prefix=f"{settings.API_V1_STR}/payments", tags=["payments"])
app.include_router(product_attributes_router, prefix=f"{settings.API_V1_STR}/product-attribute-schemas", tags=["product-attribute-schemas"])
app.include_router(ledger_router, prefix=f"{settings.API_V1_STR}/ledger", tags=["ledger"])
app.include_router(fulfillment_router, prefix=f"{settings.API_V1_STR}/fulfillment", tags=["fulfillment"])
app.include_router(knowledge_router, prefix=f"{settings.API_V1_STR}/knowledge", tags=["knowledge"])
app.include_router(support_router, prefix=f"{settings.API_V1_STR}/support", tags=["support"])

# Setup security after routers are included (configures OAuth2 bearer token for Swagger UI)
setup_security(app)


@app.on_event("startup")
async def startup_event():
    """Initialize Redis connection on startup."""
    await init_redis(settings.REDIS_URL)


@app.get("/")
async def root():
    return {"message": "Marketplace API is running"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
