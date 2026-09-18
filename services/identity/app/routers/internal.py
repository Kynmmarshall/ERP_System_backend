from fastapi import APIRouter, Depends, Response

from app.deps import get_current_claims

router = APIRouter()


@router.get("/verify", include_in_schema=False)
async def verify_session(response: Response, claims: dict = Depends(get_current_claims)) -> dict:
    """Called by the gateway's auth_request directive - never routed to a
    client directly. A non-2xx from get_current_claims already denies access;
    on success these headers are what auth_request_set forwards upstream.
    """
    response.headers["X-User-Id"] = claims["sub"]
    response.headers["X-Tenant-Id"] = claims.get("tenant_id") or ""
    response.headers["X-Roles"] = claims.get("role") or ""
    return {"status": "ok"}
