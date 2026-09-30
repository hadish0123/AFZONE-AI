from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "PRIMEVPN"
    app_env: str = "production"
    api_prefix: str = "/api/v1"
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    encryption_key: str = Field(alias="APP_ENCRYPTION_KEY")

    owner_username: str = Field(default="owner", alias="OWNER_USERNAME")
    owner_password: str = Field(alias="OWNER_PASSWORD")

    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    public_web_url: str = Field(default="http://localhost:3000", alias="PUBLIC_WEB_URL")

    billing_gib_bytes: int = 1024**3
    low_balance_warning_toman: int = 50_000

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
