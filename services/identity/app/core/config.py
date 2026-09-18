from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "identity"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://identity_app:identity_dev_password@postgres:5432/identity_db"
    log_level: str = "INFO"

    jwt_private_key_path: str = "/run/secrets/jwt_private_key.pem"
    jwt_public_key_path: str = "/run/secrets/jwt_public_key.pem"
    access_token_ttl_minutes: int = 10
    refresh_token_ttl_days: int = 14
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_secure: bool = True

    max_failed_login_attempts: int = 5
    lockout_minutes: int = 15

    # Public self-registration always creates a STUDENT account in this
    # institution (see app/routers/auth.py's /register) - staff/admin
    # accounts remain admin-provisioned only, never self-registerable.
    self_registration_institution_slug: str = "ict-main"

    # --- Admin MFA (email OTP) ---
    # "console" prints the OTP to the service log instead of emailing it: a
    # DISCLOSED development substitute (same convention as finance's
    # CamerPay test_double), never a silent mock. Production must use a real
    # sender ("brevo" or "smtp") - enforced by the validator below.
    mfa_email_provider: str = "console"
    mfa_otp_ttl_minutes: int = 10
    mfa_max_attempts: int = 5
    brevo_api_key: str = ""
    brevo_sender_email: str = "no-reply@ict-erp-system.duckdns.org"
    brevo_sender_name: str = "ICT University ERP"
    # Opt-in: only set once the URL is confirmed publicly reachable, since a
    # broken remote image renders worse than the built-in text mark.
    mfa_email_logo_url: str = ""

    # SMTP sender, for when a provider's HTTP API is unavailable but its mail
    # relay is not (Brevo's relay, Gmail app passwords, a university server).
    smtp_host: str = "smtp-relay.brevo.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # STARTTLS on 587 is the normal case; set false only for implicit TLS on
    # 465, which uses a different socket type entirely.
    smtp_starttls: bool = True

    @model_validator(mode="after")
    def _require_real_mfa_sender_in_production(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.mfa_email_provider == "brevo" and self.brevo_api_key:
            return self
        if self.mfa_email_provider == "smtp" and self.smtp_host and self.smtp_password:
            return self
        raise ValueError(
            "Production requires MFA_EMAIL_PROVIDER=brevo with a non-empty BREVO_API_KEY, "
            "or MFA_EMAIL_PROVIDER=smtp with SMTP_HOST and SMTP_PASSWORD set - "
            "admin MFA codes must never be written to logs outside development."
        )


settings = Settings()
