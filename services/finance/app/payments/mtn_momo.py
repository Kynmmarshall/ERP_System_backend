"""Real MTN MoMo Collections adapter, written for a genuine sandbox
integration but NEVER exercised against the actual MTN sandbox in this
session - no credentials have been provisioned (see phase5-plan.md). Do
not claim live sandbox validation until CAMERPAY_PROVIDER=mtn_momo is
actually run with real CAMERPAY_* credentials and independently verified.
"""
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import settings
from app.payments.protocol import InitiateResult, PaymentStatus

_BASE_URLS = {
    "sandbox": "https://sandbox.momodeveloper.mtn.com",
    "production": "https://momodeveloper.mtn.com",
}


class MtnMomoGateway:
    def __init__(self) -> None:
        self._base_url = _BASE_URLS.get(settings.camerpay_target_environment, _BASE_URLS["sandbox"])
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        if self._access_token and self._token_expires_at and datetime.now(UTC) < self._token_expires_at:
            return self._access_token

        response = await client.post(
            f"{self._base_url}/collection/token/",
            auth=(settings.camerpay_api_user, settings.camerpay_api_key),
            headers={"Ocp-Apim-Subscription-Key": settings.camerpay_subscription_key},
        )
        response.raise_for_status()
        body = response.json()
        access_token: str = body["access_token"]
        self._access_token = access_token
        # Refresh a little early rather than exactly at expiry.
        self._token_expires_at = datetime.now(UTC) + timedelta(seconds=int(body["expires_in"]) - 30)
        return access_token

    async def request_to_pay(self, *, reference: str, amount_xaf: int, payer_msisdn: str) -> InitiateResult:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._get_access_token(client)
            response = await client.post(
                f"{self._base_url}/collection/v1_0/requesttopay",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Reference-Id": reference,
                    "X-Target-Environment": settings.camerpay_target_environment,
                    "Ocp-Apim-Subscription-Key": settings.camerpay_subscription_key,
                    "Content-Type": "application/json",
                },
                json={
                    "amount": str(amount_xaf),
                    "currency": "XAF",
                    "externalId": reference,
                    "payer": {"partyIdType": "MSISDN", "partyId": payer_msisdn},
                    "payerMessage": "ICT University tuition payment",
                    "payeeNote": "Tuition invoice",
                },
            )
            response.raise_for_status()
        return InitiateResult()

    async def get_status(
        self,
        *,
        reference: str,
        requested_at: datetime,
        payer_msisdn: str,
        provider_transaction_id: str | None = None,
    ) -> PaymentStatus:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._get_access_token(client)
            response = await client.get(
                f"{self._base_url}/collection/v1_0/requesttopay/{reference}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Target-Environment": settings.camerpay_target_environment,
                    "Ocp-Apim-Subscription-Key": settings.camerpay_subscription_key,
                },
            )
            response.raise_for_status()
            provider_status = response.json()["status"]
            if provider_status == "SUCCESSFUL":
                return "SUCCESSFUL"
            if provider_status == "FAILED":
                return "FAILED"
            return "PENDING"


def new_reference() -> str:
    return str(uuid.uuid4())
