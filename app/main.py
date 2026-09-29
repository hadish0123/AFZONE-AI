from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .mcp_server import mcp
from .pasarguard import PasarGuardClient, PasarGuardError


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "afzone-ai", "version": "0.3.0"})


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


mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/pasarguard_health", pasarguard_health, methods=["GET"]),
        Mount("/", app=mcp_app),
    ],
    lifespan=lifespan,
)
