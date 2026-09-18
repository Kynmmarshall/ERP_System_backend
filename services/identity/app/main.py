import logging

from fastapi import FastAPI, Response, status

from app.core.config import settings
from app.core.db import database_is_ready
from app.routers.auth import router as auth_router
from app.routers.internal import router as internal_router
from app.routers.role_requests import router as role_requests_router
from app.routers.users import router as users_router

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="ICT University ERP - Identity Service",
    version="0.1.0",
    # Defense in depth: the gateway never proxies /docs, /redoc or
    # /openapi.json, and production does not publish this service's port
    # directly - but disable them here too so a misconfigured port publish
    # never exposes the schema.
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/v1/auth/users", tags=["users"])
app.include_router(
    role_requests_router, prefix="/api/v1/auth/role-requests", tags=["role-requests"]
)
app.include_router(internal_router, prefix="/internal", tags=["internal"], include_in_schema=False)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness: process is up. Must not depend on the database or broker."""
    return {"status": "ok", "service": settings.service_name}


@app.get("/readyz", tags=["health"])
async def readyz(response: Response) -> dict[str, str]:
    """Readiness: dependencies are reachable, so it is safe to route traffic here."""
    if not await database_is_ready():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "service": settings.service_name, "reason": "database"}
    return {"status": "ready", "service": settings.service_name}
