from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import get_settings
from .mcp_server import mcp
from .pasarguard import PasarGuardClient, PasarGuardError, gateway_token_matches


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "afzone-ai", "version": "0.2.1"})


async def pasarguard_health(_: Request) -> JSONResponse:
    """Minimal upstream/auth check. Never returns PasarGuard response data or credentials."""
    try:
        await PasarGuardClient().request("GET", "/api/admin")
        return JSONResponse({"ok": True, "pasarguard": "connected"})
    except PasarGuardError as exc:
        return JSONResponse(
            {"ok": False, "pasarguard": "unavailable", "upstream_status": exc.status_code},
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {"ok": False, "pasarguard": "unavailable"},
            status_code=503,
        )


class GatewayAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            authorization = request.headers.get("authorization", "")
            bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
            candidate = bearer or request.headers.get("x-afzone-key")
            if not gateway_token_matches(candidate, get_settings()):
                return JSONResponse(
                    {"detail": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)


mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/pasarguard-health", pasarguard_health, methods=["GET"]),
        Mount("/", app=mcp_app),
    ],
    lifespan=lifespan,
)
app.add_middleware(GatewayAuthMiddleware)
