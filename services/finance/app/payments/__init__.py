from functools import lru_cache

from app.core.config import settings
from app.payments.protocol import PaymentGateway
from app.payments.test_double import CamerPayTestDoubleGateway


@lru_cache(maxsize=1)
def get_gateway() -> PaymentGateway:
    if settings.camerpay_provider == "mtn_momo":
        from app.payments.mtn_momo import MtnMomoGateway

        return MtnMomoGateway()
    if settings.camerpay_provider == "camerpay":
        from app.payments.camerpay import CamerPayGateway

        return CamerPayGateway()
    return CamerPayTestDoubleGateway()
