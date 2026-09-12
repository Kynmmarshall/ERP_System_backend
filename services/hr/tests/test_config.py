import pytest

from app.core.config import Settings


def test_production_rejects_the_insecure_default_qr_secret() -> None:
    with pytest.raises(ValueError, match="HR_QR_SIGNING_SECRET"):
        Settings(environment="production", hr_qr_signing_secret="dev-only-insecure-default-change-me")


def test_production_accepts_a_real_qr_secret() -> None:
    settings = Settings(environment="production", hr_qr_signing_secret="a-real-random-secret")
    assert settings.hr_qr_signing_secret == "a-real-random-secret"


def test_development_allows_the_insecure_default_qr_secret() -> None:
    settings = Settings(environment="development", hr_qr_signing_secret="dev-only-insecure-default-change-me")
    assert settings.hr_qr_signing_secret == "dev-only-insecure-default-change-me"
