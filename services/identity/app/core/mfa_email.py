"""Admin-MFA one-time-code delivery.

Two selectable providers (MFA_EMAIL_PROVIDER):
  - "brevo"   : real Brevo transactional email API. Contract per
                https://developers.brevo.com/reference/sendtransacemail
                (POST /v3/smtp/email, `api-key` header). NOT exercised
                against a live Brevo account in this session - no key was
                provisioned here, so do not claim live validation until it
                has actually been run and checked.
  - "console" : DISCLOSED development substitute - writes the code to the
                service log instead of sending mail, so the flow is fully
                testable without a provider account. app/core/config.py
                refuses to start in production with this selected.
"""
import logging

import httpx

from app.core.config import settings
from app.core.mfa_email_template import render_mfa_html, render_mfa_text

logger = logging.getLogger("identity.mfa")

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


async def send_mfa_code(*, to_email: str, to_name: str, code: str) -> None:
    if settings.mfa_email_provider == "brevo":
        await _send_via_brevo(to_email=to_email, to_name=to_name, code=code)
        return
    # Deliberately logged only in the console/dev provider - a real code must
    # never reach the logs in production (see config validator).
    logger.warning("[dev console MFA provider] code for %s: %s", to_email, code)


async def _send_via_brevo(*, to_email: str, to_name: str, code: str) -> None:
    minutes = settings.mfa_otp_ttl_minutes
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            _BREVO_URL,
            headers={
                "api-key": settings.brevo_api_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
            json={
                "sender": {"name": settings.brevo_sender_name, "email": settings.brevo_sender_email},
                "to": [{"email": to_email, "name": to_name}],
                "subject": f"{code} is your ICT University ERP sign-in code",
                "textContent": render_mfa_text(to_name=to_name, code=code, minutes=minutes),
                "htmlContent": render_mfa_html(to_name=to_name, code=code, minutes=minutes),
            },
        )
        response.raise_for_status()
