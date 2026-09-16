import logging

from fastapi import Depends, FastAPI, Response, status

from app.core.config import settings
from app.core.db import database_is_ready
from app.deps import get_current_claims
from app.routers.academic import router as academic_router
from app.routers.attendance import router as attendance_router
from app.routers.courses import router as courses_router
from app.routers.exams import router as exams_router
from app.routers.grades import router as grades_router
from app.routers.reports import router as reports_router
from app.schemas import PrincipalResponse

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="ICT University ERP - Academic Service",
    version="0.1.0",
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None if settings.environment == "production" else "/redoc",
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)

app.include_router(academic_router, prefix="/api/v1/academic", tags=["academic"])
app.include_router(courses_router, prefix="/api/v1/academic", tags=["courses"])
app.include_router(attendance_router, prefix="/api/v1/academic", tags=["attendance"])
app.include_router(grades_router, prefix="/api/v1/academic", tags=["grades"])
app.include_router(exams_router, prefix="/api/v1/academic", tags=["exams"])
app.include_router(reports_router, prefix="/api/v1/academic", tags=["reports"])


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


@app.get("/api/v1/academic/me", tags=["auth"])
async def me(claims: dict = Depends(get_current_claims)) -> PrincipalResponse:
    """Exists to prove this service verifies the JWT itself (signature, issuer,
    audience, expiry) rather than only trusting gateway-forwarded headers.
    """
    return PrincipalResponse(
        user_id=claims["sub"],
        tenant_id=claims.get("tenant_id"),
        role=claims.get("role", ""),
    )
