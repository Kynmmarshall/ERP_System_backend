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


settings = Settings()
