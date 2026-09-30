from urllib.parse import urljoin, urlparse

import httpx

from app.core.security import decrypt_secret


class PasarGuardError(RuntimeError):
    pass


class PasarGuardClient:
    def __init__(self, base_url: str, encrypted_api_token: str, timeout: float = 20.0):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("invalid PasarGuard base URL")
        self.base_url = base_url.rstrip("/") + "/"
        self.api_token = decrypt_secret(encrypted_api_token)
        self.timeout = timeout

    async def request(self, method: str, path: str, *, params=None, json=None):
        if not path.startswith("/api/") or ".." in path:
            raise ValueError("only PasarGuard /api/* paths are allowed")
        url = urljoin(self.base_url, path.lstrip("/"))
        if urlparse(url).netloc != urlparse(self.base_url).netloc:
            raise ValueError("cross-host request blocked")

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            headers={"X-Api-Key": self.api_token},
        ) as client:
            response = await client.request(method, url, params=params, json=json)

        if response.status_code >= 400:
            raise PasarGuardError(
                f"PasarGuard request failed with HTTP {response.status_code}"
            )
        if not response.content:
            return None
        return response.json()

    async def health(self):
        return await self.request("GET", "/api/admin")

    async def list_groups(self):
        return await self.request("GET", "/api/groups")

    async def list_users(self, **params):
        return await self.request("GET", "/api/users", params=params)

    async def create_user(self, payload: dict):
        return await self.request("POST", "/api/user", json=payload)

    async def update_user(self, user_id: int, payload: dict):
        return await self.request("PUT", f"/api/user/{user_id}", json=payload)

    async def delete_user(self, user_id: int):
        return await self.request("DELETE", f"/api/user/{user_id}")
