from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "academic"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://academic_app:academic_dev_password@postgres:5432/academic_db"
    rabbitmq_url: str = "amqp://erp_app:erp_dev_password@rabbitmq:5672/"
    log_level: str = "INFO"


settings = Settings()
