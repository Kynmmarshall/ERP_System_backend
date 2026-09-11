import logging

from fastapi import FastAPI, Response, status

from app.core.config import settings
from app.core.db import database_is_ready

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="ICT University ERP - Identity Service",
    version="0.1.0",
    # Swagger/OpenAPI stay enabled here only for internal/dev use; the gateway
    # does not expose this service's docs publicly in production.
)


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
