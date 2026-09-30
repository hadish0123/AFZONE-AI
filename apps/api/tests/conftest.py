import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("APP_ENCRYPTION_KEY", "fh4fj-6lyWa0QXAdcC2mKtfF1Gux7xcN2KkFGhH2MH4=")
os.environ.setdefault("OWNER_USERNAME", "owner")
os.environ.setdefault("OWNER_PASSWORD", "test-owner-password")
