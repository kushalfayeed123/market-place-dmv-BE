from app.core.config import settings
print(f"DATABASE_URL: {settings.DATABASE_URL}")
print(f"REDIS_URL: {settings.REDIS_URL}")
print(f"JWT_SECRET_KEY: {settings.JWT_SECRET_KEY}")