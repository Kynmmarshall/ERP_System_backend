from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "hr"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://hr_app:hr_dev_password@postgres:5432/hr_db"
    log_level: str = "INFO"

    jwt_public_key_path: str = "/run/secrets/jwt_public_key.pem"
    hr_qr_signing_secret: str = "dev-only-insecure-default-change-me"


settings = Settings()
