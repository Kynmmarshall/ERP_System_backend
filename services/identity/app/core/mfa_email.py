"""Admin-MFA one-time-code delivery.

Three selectable providers (MFA_EMAIL_PROVIDER):
  - "brevo"   : real Brevo transactional email API. Contract per
                https://developers.brevo.com/reference/sendtransacemail
                (POST /v3/smtp/email, `api-key` header). NOT exercised
                against a live Brevo account in this session - no key was
                provisioned here, so do not claim live validation until it
                has actually been run and checked.
  - "smtp"    : plain SMTP submission. Exists because a provider's HTTP API
                and its mail relay are separately gated - Brevo answered
                `401 {"message":"API Key is not enabled"}` on the API while
                the relay stayed usable. Also covers Gmail app passwords and
                a university mail server.
  - "console" : DISCLOSED development substitute - writes the code to the
                service log instead of sending mail, so the flow is fully
                testable without a provider account. Codes are also pinned
                to 123456 under this provider (see core/security.py).
                app/core/config.py refuses to start in production with this
                selected.
"""
import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import settings
from app.core.mfa_email_template import render_mfa_html, render_mfa_text

logger = logging.getLogger("identity.mfa")

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


async def send_mfa_code(*, to_email: str, to_name: str, code: str) -> None:
    if settings.mfa_email_provider == "brevo":
        await _send_via_brevo(to_email=to_email, to_name=to_name, code=code)
        return
    if settings.mfa_email_provider == "smtp":
        await _send_via_smtp(to_email=to_email, to_name=to_name, code=code)
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


def _build_message(*, to_email: str, to_name: str, code: str) -> EmailMessage:
    minutes = settings.mfa_otp_ttl_minutes
    message = EmailMessage()
    message["Subject"] = f"{code} is your ICT University ERP sign-in code"
    message["From"] = f"{settings.brevo_sender_name} <{settings.brevo_sender_email}>"
    message["To"] = f"{to_name} <{to_email}>"
    message.set_content(render_mfa_text(to_name=to_name, code=code, minutes=minutes))
    message.add_alternative(
        render_mfa_html(to_name=to_name, code=code, minutes=minutes), subtype="html"
    )
    return message


def _send_message_blocking(message: EmailMessage) -> None:
    if settings.smtp_starttls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
        return
    # Implicit TLS (usually port 465) is a different socket class, not a flag.
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def _send_via_smtp(*, to_email: str, to_name: str, code: str) -> None:
    """smtplib is synchronous, so it runs on a worker thread rather than
    stalling the event loop for the duration of an SMTP conversation.
    Using it keeps the dependency set unchanged - no new pinned package."""
    message = _build_message(to_email=to_email, to_name=to_name, code=code)
    await asyncio.to_thread(_send_message_blocking, message)
