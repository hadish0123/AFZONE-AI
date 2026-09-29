from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", validation_alias="APP_ENV")
    pasarguard_base_url: AnyHttpUrl = Field(validation_alias="PASARGUARD_BASE_URL")
    pasarguard_api_key: SecretStr = Field(validation_alias="PASARGUARD_API_KEY")
    gateway_token: SecretStr = Field(validation_alias="AFZONE_GATEWAY_TOKEN")
    request_timeout_seconds: float = Field(default=15.0, ge=1, le=120, validation_alias="REQUEST_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
