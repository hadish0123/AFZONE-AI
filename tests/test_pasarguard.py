from pydantic import SecretStr
from pydantic.networks import AnyHttpUrl
import httpx
import pytest

from app.config import Settings
from app.pasarguard import PasarGuardClient, redact_sensitive, validate_api_path


def settings() -> Settings:
    return Settings.model_construct(
        app_env="test",
        pasarguard_base_url=AnyHttpUrl("https://panel.example.com"),
        pasarguard_api_key=SecretStr("pg_key_test"),
        gateway_token=SecretStr("gateway-test"),
        request_timeout_seconds=5.0,
    )


def test_path_guard():
    assert validate_api_path("/api/admins") == "/api/admins"
    with pytest.raises(ValueError):
        validate_api_path("/api/setup/owner")
    with pytest.raises(ValueError):
        validate_api_path("https://evil.example/api/admins")


def test_redaction():
    value = {"api_key": "secret", "nested": {"password": "x", "name": "ok"}}
    assert redact_sensitive(value) == {"api_key": "<redacted>", "nested": {"password": "<redacted>", "name": "ok"}}


@pytest.mark.asyncio
async def test_client_auth_and_response():
    async def handler(request: httpx.Request):
        assert request.headers["X-Api-Key"] == "pg_key_test"
        return httpx.Response(200, json={"admins": [], "api_key": "should-hide"})

    client = PasarGuardClient(settings(), transport=httpx.MockTransport(handler))
    result = await client.request("GET", "/api/admins")
    assert result["ok"] is True
    assert result["data"]["api_key"] == "<redacted>"
