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

    # camerpay.biz aggregator API (camerpay_provider="camerpay") - distinct
    # credential set from the direct mtn_momo mode above.
    camerpay_token: str = ""
    camerpay_base_url: str = "https://camerpay.biz/api"
    camerpay_callback_secret: str = ""
    camerpay_merchant_callback_url: str = ""
    camerpay_merchant_return_url: str = ""


settings = Settings()
