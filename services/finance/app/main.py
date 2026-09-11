import logging

from fastapi import Depends, FastAPI, Response, status

from app.core.config import settings
from app.core.db import database_is_ready
from app.deps import get_current_claims
from app.routers.finance import router as finance_router
from app.schemas import PrincipalResponse

logging.basicConfig(level=settings.log_level)

app = FastAPI(title="ICT University ERP - Finance & Marketing Service", version="0.1.0")

app.include_router(finance_router, prefix="/api/v1/finance", tags=["finance"])


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


@app.get("/api/v1/finance/me", tags=["auth"])
async def me(claims: dict = Depends(get_current_claims)) -> PrincipalResponse:
    """Exists to prove this service verifies the JWT itself (signature, issuer,
    audience, expiry) rather than only trusting gateway-forwarded headers.
    """
    return PrincipalResponse(
        user_id=claims["sub"],
        tenant_id=claims.get("tenant_id"),
        campus_id=claims.get("campus_id"),
        role=claims.get("role", ""),
    )
