import hmac
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import Settings, get_settings


class PasarGuardError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


BLOCKED_PATH_PREFIXES = (
    "/api/setup",
    "/api/admin/token",
    "/api/admin/miniapp/token",
)

SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "hashed_password",
    "password",
    "private_key",
    "secret",
    "token",
}


def validate_api_path(path: str) -> str:
    if not path.startswith("/api/") and path != "/api":
        raise ValueError("Only PasarGuard /api paths are allowed")
    if "://" in path or ".." in path or "\\" in path:
        raise ValueError("Invalid API path")
    if any(path.startswith(prefix) for prefix in BLOCKED_PATH_PREFIXES):
        raise ValueError("Authentication/setup endpoints are intentionally blocked")
    return path


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                output[key] = "<redacted>"
            else:
                output[key] = redact_sensitive(item)
        return output
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


class PasarGuardClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings or get_settings()
        self._transport = transport

    def _url(self, path: str) -> str:
        validate_api_path(path)
        base = str(self.settings.pasarguard_base_url).rstrip("/") + "/"
        url = urljoin(base, path.lstrip("/"))
        if urlparse(url).netloc != urlparse(base).netloc:
            raise ValueError("Cross-origin PasarGuard requests are blocked")
        return url

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("Unsupported HTTP method")

        headers = {
            "X-Api-Key": self.settings.pasarguard_api_key.get_secret_value(),
            "Accept": "application/json",
            "User-Agent": "AFZONE-AI/0.2",
        }

        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            response = await client.request(method, self._url(path), params=params, json=json_body, headers=headers)

        if response.status_code == 204:
            data: Any = None
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:8000]}

        if response.status_code >= 400:
            detail = redact_sensitive(data)
            raise PasarGuardError(
                f"PasarGuard returned HTTP {response.status_code}",
                status_code=response.status_code,
                detail=detail,
            )

        return {"ok": True, "status_code": response.status_code, "data": redact_sensitive(data)}


def gateway_token_matches(candidate: str | None, settings: Settings | None = None) -> bool:
    if not candidate:
        return False
    expected = (settings or get_settings()).gateway_token.get_secret_value()
    return hmac.compare_digest(candidate, expected)
