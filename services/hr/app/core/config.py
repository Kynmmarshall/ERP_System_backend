from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "hr"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://hr_app:hr_dev_password@postgres:5432/hr_db"
    log_level: str = "INFO"


settings = Settings()
