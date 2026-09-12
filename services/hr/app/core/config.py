from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_QR_SECRET_DEFAULT = "dev-only-insecure-default-change-me"


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "hr"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://hr_app:hr_dev_password@postgres:5432/hr_db"
    log_level: str = "INFO"

    jwt_public_key_path: str = "/run/secrets/jwt_public_key.pem"
    hr_qr_signing_secret: str = _INSECURE_QR_SECRET_DEFAULT

    @model_validator(mode="after")
    def _reject_insecure_qr_secret_in_production(self) -> "Settings":
        # Fail closed (OWASP A05 - Security Misconfiguration): a real
        # deployment must never silently run with the checked-in dev HMAC
        # secret for QR shift-attendance tokens.
        if self.environment == "production" and self.hr_qr_signing_secret == _INSECURE_QR_SECRET_DEFAULT:
            raise ValueError("HR_QR_SIGNING_SECRET must be set to a real secret in production")
        return self


settings = Settings()
