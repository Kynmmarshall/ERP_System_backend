from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "identity"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://identity_app:identity_dev_password@postgres:5432/identity_db"
    log_level: str = "INFO"


settings = Settings()
