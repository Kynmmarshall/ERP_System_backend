from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service configuration sourced from environment variables (.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "finance"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://finance_app:finance_dev_password@postgres:5432/finance_db"
    rabbitmq_url: str = "amqp://erp_app:erp_dev_password@rabbitmq:5672/"
    log_level: str = "INFO"

    jwt_public_key_path: str = "/run/secrets/jwt_public_key.pem"

    camerpay_provider: str = "test_double"
    camerpay_subscription_key: str = ""
    camerpay_api_user: str = ""
    camerpay_api_key: str = ""
    camerpay_target_environment: str = "sandbox"


settings = Settings()
