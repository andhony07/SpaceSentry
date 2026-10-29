"""SpaceSentry backend entrypoint.

Security posture (Phase 1):
- binds to localhost only (see core.config),
- CORS restricted to the local frontend dev origin,
- read-only endpoints only — no destructive operation exists yet,
- structured logging with filesystem metadata never logged as content.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import analysis, cleanup, scans, system
from app.core.config import get_settings
from app.core.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
logger.info("Starting SpaceSentry backend (host=%s port=%s)", settings.host, settings.port)

app = FastAPI(
    title="SpaceSentry API",
    version="0.1.0",
    description="Safe storage intelligence: read-only scanning for Phase 1.",
)

# Restrictive CORS: only the local frontend, no credentials, explicit methods.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.allowed_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _is_local_host(host_header: str | None) -> bool:
    """Accept Host values that unambiguously name the loopback interface."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    host = host.rsplit(":", 1)[0] if "]" not in host else host.rsplit(":", 1)[0]
    host = host.strip("[]")
    return host in _LOCAL_HOSTNAMES


@app.middleware("http")
async def local_binding_guard(request: Request, call_next):
    """Host/Origin hardening for a localhost-only API.

    CORS alone cannot stop every local-browser threat model:
    - DNS rebinding lets a malicious page make *same-origin* requests to a
      hostname resolving at 127.0.0.1; the Host header still reveals the
      deception and is rejected here.
    - Simple cross-site requests (no preflight) execute regardless of CORS;
      a wrong Origin header is rejected here for defense in depth.
    Read-only analysis loses nothing from this restriction.
    """
    if not _is_local_host(request.headers.get("host")):
        return JSONResponse(
            status_code=403,
            content={"code": "foreign_host", "message": "SpaceSentry only accepts requests addressed to the local machine."},
        )
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.allowed_origins:
        return JSONResponse(
            status_code=403,
            content={"code": "foreign_origin", "message": "Cross-site browser requests are not accepted."},
        )
    return await call_next(request)


# Cleanup resolves this exact registry via request.app.state, keeping scans
# isolated per FastAPI application and avoiding process-global scan state.
app.state.scan_registry = scans.registry

app.include_router(system.router, prefix="/api")
app.include_router(scans.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(cleanup.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "spacesentry-backend", "mode": "read-only"}
