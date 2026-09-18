"""Admin-MFA delivery: the SMTP sender, and the production guard that decides
which providers are allowed to be selected at all.
"""
import smtplib
from email.message import EmailMessage

import pytest
from pydantic import ValidationError

from app.core import mfa_email
from app.core.config import Settings, settings

_PRODUCTION_BASE = {
    "environment": "production",
    "brevo_api_key": "",
    "smtp_host": "",
    "smtp_password": "",
}


def _production_settings(**overrides) -> Settings:
    return Settings(**{**_PRODUCTION_BASE, **overrides})


def test_production_rejects_the_console_provider() -> None:
    with pytest.raises(ValidationError, match="admin MFA codes must never be written to logs"):
        _production_settings(mfa_email_provider="console")


def test_production_rejects_brevo_without_a_key() -> None:
    with pytest.raises(ValidationError):
        _production_settings(mfa_email_provider="brevo")


def test_production_accepts_brevo_with_a_key() -> None:
    assert _production_settings(mfa_email_provider="brevo", brevo_api_key="xkeysib-real").environment == "production"


def test_production_rejects_smtp_without_a_host() -> None:
    with pytest.raises(ValidationError):
        _production_settings(mfa_email_provider="smtp", smtp_password="secret")


def test_production_rejects_smtp_without_a_password() -> None:
    """A host alone would silently attempt unauthenticated relay."""
    with pytest.raises(ValidationError):
        _production_settings(mfa_email_provider="smtp", smtp_host="smtp-relay.brevo.com")


def test_production_accepts_fully_configured_smtp() -> None:
    configured = _production_settings(
        mfa_email_provider="smtp",
        smtp_host="smtp-relay.brevo.com",
        smtp_password="secret",
    )
    assert configured.mfa_email_provider == "smtp"


def test_development_still_allows_the_console_provider() -> None:
    assert Settings(environment="development", mfa_email_provider="console").mfa_email_provider == "console"


class _FakeSMTP:
    """Records what would have gone over the wire. Never opens a socket."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.sent: EmailMessage | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent = message


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)
    monkeypatch.setattr(settings, "mfa_email_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp-relay.brevo.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "mailer@example.com")
    monkeypatch.setattr(settings, "smtp_password", "secret")
    monkeypatch.setattr(settings, "smtp_starttls", True)
    return _FakeSMTP


async def test_smtp_provider_sends_a_login_code(fake_smtp) -> None:
    await mfa_email.send_mfa_code(to_email="admin@example.com", to_name="Ada", code="424242")

    assert len(fake_smtp.instances) == 1
    sent = fake_smtp.instances[0]
    assert sent.host == "smtp-relay.brevo.com"
    assert sent.login_args == ("mailer@example.com", "secret")
    assert sent.sent is not None
    assert "admin@example.com" in sent.sent["To"]
    assert "424242" in sent.sent["Subject"]


async def test_smtp_provider_upgrades_to_tls_before_authenticating(fake_smtp) -> None:
    """Sending credentials over a cleartext socket would leak them."""
    await mfa_email.send_mfa_code(to_email="admin@example.com", to_name="Ada", code="424242")

    assert fake_smtp.instances[0].started_tls is True


async def test_smtp_code_is_not_logged(fake_smtp, caplog) -> None:
    """The console provider logs the code on purpose; a real sender must not."""
    with caplog.at_level("DEBUG", logger="identity.mfa"):
        await mfa_email.send_mfa_code(to_email="admin@example.com", to_name="Ada", code="424242")

    assert "424242" not in caplog.text


async def test_smtp_carries_both_a_text_and_an_html_part(fake_smtp) -> None:
    await mfa_email.send_mfa_code(to_email="admin@example.com", to_name="Ada", code="424242")

    subtypes = {part.get_content_subtype() for part in fake_smtp.instances[0].sent.walk()}
    assert {"plain", "html"} <= subtypes


async def test_implicit_tls_skips_starttls(fake_smtp, monkeypatch) -> None:
    """Port 465 is already encrypted; calling STARTTLS on it errors out."""
    monkeypatch.setattr(settings, "smtp_starttls", False)
    monkeypatch.setattr(settings, "smtp_port", 465)

    await mfa_email.send_mfa_code(to_email="admin@example.com", to_name="Ada", code="424242")

    sent = fake_smtp.instances[0]
    assert sent.started_tls is False
    assert sent.port == 465
    assert sent.sent is not None
