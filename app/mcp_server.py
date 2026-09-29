import asyncio
from typing import Any, Literal

from pydantic import AnyHttpUrl
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP

from .catalog import ACTIONS, READ_ONLY_PATHS, RESOURCE_ROUTES
from .config import get_settings
from .oauth_provider import SingleUserOAuthProvider
from .pasarguard import PasarGuardClient, PasarGuardError, validate_api_path

settings = get_settings()
public_url = str(settings.public_url).rstrip("/")
resource_url = f"{public_url}/mcp"
oauth_provider = SingleUserOAuthProvider(settings)

mcp = FastMCP(
    name="AFZONE PasarGuard Manager",
    instructions=(
        "Manage the connected PasarGuard panel. Read operations may run immediately. "
        "Never perform POST, PUT, PATCH, or DELETE unless the user explicitly approved the exact change; "
        "mutation tools require confirm=true. Authentication/bootstrap endpoints are unavailable."
    ),
    stateless_http=True,
    json_response=True,
    auth_server_provider=oauth_provider,
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(public_url),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[settings.oauth_scope],
            default_scopes=[settings.oauth_scope],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[settings.oauth_scope],
        resource_server_url=AnyHttpUrl(resource_url),
        validate_token_resource=True,
    ),
)


@mcp.custom_route("/login", methods=["GET"])
async def login_page(request: Request) -> Response:
    state = request.query_params.get("state")
    if not state:
        raise HTTPException(400, "Missing state")
    return await oauth_provider.login_page(state)


@mcp.custom_route("/login/callback", methods=["POST"])
async def login_callback(request: Request) -> Response:
    return await oauth_provider.login_callback(request)


def _confirmation(method: str, path: str, payload: Any = None) -> dict[str, Any]:
    return {
        "ok": False,
        "confirmation_required": True,
        "method": method,
        "path": path,
        "payload": payload,
        "message": "Ask the user to confirm this exact mutation, then call again with confirm=true.",
    }


def _error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, PasarGuardError):
        return {
            "ok": False,
            "error": str(exc),
            "status_code": exc.status_code,
            "detail": exc.detail,
        }
    return {"ok": False, "error": str(exc)}


@mcp.tool()
async def panel_request(
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"],
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | list[Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Call any operational PasarGuard /api endpoint. Mutations require confirm=true. Login/setup endpoints are blocked."""
    try:
        validate_api_path(path)
        if method != "GET" and not confirm:
            return _confirmation(method, path, body)
        return await PasarGuardClient().request(method, path, params=params, json_body=body)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def list_resource(resource: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """List a core PasarGuard resource: admins, users, groups, hosts, nodes, cores, user_templates, client_templates, admin_roles, api_keys."""
    try:
        route = RESOURCE_ROUTES[resource]
        if not route.list_path:
            raise ValueError(f"Resource {resource} has no list endpoint")
        return await PasarGuardClient().request("GET", route.list_path, params=params)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def get_resource(resource: str, resource_id: int, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get one PasarGuard resource by numeric ID."""
    try:
        route = RESOURCE_ROUTES[resource]
        if not route.get_path:
            raise ValueError(f"Resource {resource} has no detail endpoint")
        return await PasarGuardClient().request("GET", route.get_path.format(id=resource_id), params=params)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def create_resource(resource: str, body: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    """Create a PasarGuard resource. Requires explicit user confirmation via confirm=true."""
    try:
        route = RESOURCE_ROUTES[resource]
        if not route.create_path:
            raise ValueError(f"Resource {resource} cannot be created")
        if not confirm:
            return _confirmation("POST", route.create_path, body)
        return await PasarGuardClient().request("POST", route.create_path, json_body=body)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def update_resource(
    resource: str,
    resource_id: int,
    body: dict[str, Any],
    confirm: bool = False,
) -> dict[str, Any]:
    """Update a PasarGuard resource by ID. Requires explicit user confirmation via confirm=true."""
    try:
        route = RESOURCE_ROUTES[resource]
        if not route.update_path:
            raise ValueError(f"Resource {resource} cannot be updated")
        path = route.update_path.format(id=resource_id)
        if not confirm:
            return _confirmation(route.update_method, path, body)
        return await PasarGuardClient().request(route.update_method, path, json_body=body)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def delete_resource(resource: str, resource_id: int, confirm: bool = False) -> dict[str, Any]:
    """Delete a PasarGuard resource by ID. Always requires explicit user confirmation via confirm=true."""
    try:
        route = RESOURCE_ROUTES[resource]
        if not route.delete_path:
            raise ValueError(f"Resource {resource} cannot be deleted")
        path = route.delete_path.format(id=resource_id)
        if not confirm:
            return _confirmation("DELETE", path)
        return await PasarGuardClient().request("DELETE", path)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def run_action(
    resource: str,
    resource_id: int,
    action: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run a named resource action such as reset_usage, reconnect, sync, revoke_subscription, restart, or realtime_stats."""
    try:
        method, template = ACTIONS[resource][action]
        path = template.format(id=resource_id)
        if method != "GET" and not confirm:
            return _confirmation(method, path, body)
        return await PasarGuardClient().request(method, path, params=params, json_body=body)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def get_panel_info(name: str) -> dict[str, Any]:
    """Read settings/system/inbound/worker information. Names: settings, general_settings, system, system_resources, system_users, inbounds, inbound_details, wireguard_subnets, workers_health."""
    try:
        path = READ_ONLY_PATHS[name]
        return await PasarGuardClient().request("GET", path)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def update_settings(body: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    """Update PasarGuard settings. Requires explicit user confirmation via confirm=true."""
    path = "/api/settings"
    if not confirm:
        return _confirmation("PUT", path, body)
    try:
        return await PasarGuardClient().request("PUT", path, json_body=body)
    except Exception as exc:
        return _error(exc)


@mcp.tool()
async def panel_overview() -> dict[str, Any]:
    """Return a compact overview of admins, users, nodes, groups, hosts, and system health."""
    client = PasarGuardClient()
    calls = {
        "admins": client.request("GET", "/api/admins", params={"limit": 1}),
        "users": client.request("GET", "/api/users", params={"limit": 1}),
        "nodes": client.request("GET", "/api/nodes", params={"limit": 200}),
        "groups": client.request("GET", "/api/groups", params={"limit": 1}),
        "hosts": client.request("GET", "/api/hosts"),
        "workers": client.request("GET", "/api/workers/health"),
    }
    results = await asyncio.gather(*calls.values(), return_exceptions=True)
    overview: dict[str, Any] = {"ok": True}
    for key, result in zip(calls, results):
        overview[key] = _error(result) if isinstance(result, Exception) else result
    return overview
