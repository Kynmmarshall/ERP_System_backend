from pydantic import BaseModel


class PrincipalResponse(BaseModel):
    """Reflects the verified JWT claims - proves this service independently
    validated the token itself rather than trusting gateway headers alone."""

    user_id: str
    tenant_id: str | None
    campus_id: str | None
    role: str
