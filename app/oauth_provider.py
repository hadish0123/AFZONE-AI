import hmac
import html
import secrets
import time

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import Settings


class SingleUserOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.public_url = str(settings.public_url).rstrip("/")
        self.login_url = f"{self.public_url}/login"
        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.auth_codes: dict[str, AuthorizationCode] = {}
        self.access_tokens: dict[str, AccessToken] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.state_mapping: dict[str, dict[str, str | None]] = {}

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        state_key = secrets.token_urlsafe(32)
        self.state_mapping[state_key] = {
            "oauth_state": params.state,
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "redirect_uri_provided_explicitly": str(params.redirect_uri_provided_explicitly),
            "client_id": client.client_id,
            "resource": params.resource,
            "scopes": " ".join(params.scopes or [self.settings.oauth_scope]),
        }
        return f"{self.login_url}?state={state_key}"

    async def login_page(self, state: str) -> HTMLResponse:
        if not state or state not in self.state_mapping:
            raise HTTPException(400, "Invalid or expired authorization state")
        safe_state = html.escape(state, quote=True)
        safe_action = html.escape(f"{self.public_url}/login/callback", quote=True)
        safe_username = html.escape(self.settings.oauth_username, quote=True)
        return HTMLResponse(
            f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AFZONE PasarGuard Manager</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1220;color:#eef2ff;margin:0;display:grid;place-items:center;min-height:100vh}}
main{{width:min(92vw,420px);background:#111a2d;border:1px solid #26324a;border-radius:18px;padding:28px;box-shadow:0 20px 60px #0007}}
h1{{font-size:22px;margin:0 0 8px}}p{{color:#aab6cf;line-height:1.8}}label{{display:block;margin:18px 0 8px}}
input{{box-sizing:border-box;width:100%;padding:12px 14px;border-radius:10px;border:1px solid #33415c;background:#0b1220;color:#fff}}
button{{width:100%;margin-top:18px;padding:12px;border:0;border-radius:10px;background:#eef2ff;color:#0b1220;font-weight:700;cursor:pointer}}
small{{display:block;color:#7f8ca8;margin-top:14px;line-height:1.7}}
</style>
</head><body><main>
<h1>AFZONE PasarGuard Manager</h1>
<p>برای اتصال خصوصی ChatGPT به پنل پاسارگاد، رمز اتصال افزونه را وارد کنید.</p>
<form action="{safe_action}" method="post">
<input type="hidden" name="state" value="{safe_state}">
<input type="hidden" name="username" value="{safe_username}">
<label for="password">رمز اتصال</label>
<input id="password" type="password" name="password" autocomplete="current-password" required autofocus>
<button type="submit">اتصال به ChatGPT</button>
</form>
<small>این رمز مستقل از رمز پنل و API Key پاسارگاد است.</small>
</main></body></html>"""
        )

    async def login_callback(self, request: Request) -> Response:
        form = await request.form()
        state = form.get("state")
        username = form.get("username")
        password = form.get("password")
        if not all(isinstance(value, str) for value in (state, username, password)):
            raise HTTPException(400, "Missing authorization fields")
        if state not in self.state_mapping:
            raise HTTPException(400, "Invalid or expired authorization state")
        if not hmac.compare_digest(username, self.settings.oauth_username):
            raise HTTPException(401, "Invalid credentials")
        if not hmac.compare_digest(password, self.settings.oauth_password.get_secret_value()):
            raise HTTPException(401, "Invalid credentials")

        state_data = self.state_mapping.pop(state)
        redirect_uri = state_data["redirect_uri"]
        code_challenge = state_data["code_challenge"]
        client_id = state_data["client_id"]
        if not redirect_uri or not code_challenge or not client_id:
            raise HTTPException(400, "Invalid authorization state")

        code = f"afz_code_{secrets.token_urlsafe(32)}"
        scopes = (state_data.get("scopes") or self.settings.oauth_scope).split()
        self.auth_codes[code] = AuthorizationCode(
            code=code,
            client_id=client_id,
            redirect_uri=AnyHttpUrl(redirect_uri),
            redirect_uri_provided_explicitly=state_data["redirect_uri_provided_explicitly"] == "True",
            expires_at=time.time() + 300,
            scopes=scopes,
            code_challenge=code_challenge,
            resource=state_data.get("resource"),
            subject=self.settings.oauth_username,
        )
        return RedirectResponse(
            construct_redirect_uri(
                redirect_uri,
                code=code,
                state=state_data.get("oauth_state"),
                iss=self.public_url,
            ),
            status_code=302,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self.auth_codes.get(authorization_code)
        if not code or code.client_id != client.client_id or code.expires_at < time.time():
            self.auth_codes.pop(authorization_code, None)
            return None
        return code

    def _new_access_token(
        self,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str | None,
    ) -> AccessToken:
        raw = f"afz_at_{secrets.token_urlsafe(48)}"
        token = AccessToken(
            token=raw,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 3600,
            resource=resource,
            subject=subject,
            claims={"iss": self.public_url},
        )
        self.access_tokens[raw] = token
        return token

    def _new_refresh_token(
        self,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str | None,
    ) -> RefreshToken:
        raw = f"afz_rt_{secrets.token_urlsafe(48)}"
        token = RefreshToken(
            token=raw,
            client_id=client_id,
            scopes=scopes,
            expires_at=int(time.time()) + 30 * 24 * 3600,
            resource=resource,
            subject=subject,
        )
        self.refresh_tokens[raw] = token
        return token

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        stored = self.auth_codes.pop(authorization_code.code, None)
        if not stored or stored.client_id != client.client_id or stored.expires_at < time.time():
            raise ValueError("Invalid authorization code")
        access = self._new_access_token(client.client_id, stored.scopes, stored.resource, stored.subject)
        refresh = self._new_refresh_token(client.client_id, stored.scopes, stored.resource, stored.subject)
        return OAuthToken(
            access_token=access.token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh.token,
            scope=" ".join(stored.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = self.access_tokens.get(token)
        if not access:
            return None
        if access.expires_at and access.expires_at < time.time():
            self.access_tokens.pop(token, None)
            return None
        return access

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token = self.refresh_tokens.get(refresh_token)
        if not token or token.client_id != client.client_id:
            return None
        if token.expires_at and token.expires_at < time.time():
            self.refresh_tokens.pop(refresh_token, None)
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        stored = self.refresh_tokens.pop(refresh_token.token, None)
        if not stored or stored.client_id != client.client_id:
            raise ValueError("Invalid refresh token")
        requested = scopes or stored.scopes
        if not set(requested).issubset(set(stored.scopes)):
            raise ValueError("Requested scopes exceed the original grant")
        access = self._new_access_token(client.client_id, requested, stored.resource, stored.subject)
        replacement = self._new_refresh_token(client.client_id, requested, stored.resource, stored.subject)
        return OAuthToken(
            access_token=access.token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=replacement.token,
            scope=" ".join(requested),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.access_tokens.pop(token.token, None)
        else:
            self.refresh_tokens.pop(token.token, None)
