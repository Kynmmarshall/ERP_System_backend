"""Real adapter for the camerpay.biz aggregator API (a hosted-redirect
gateway distinct from the direct MTN MoMo Collections mode in
mtn_momo.py). Contract verified against the public docs at
https://camerpay.biz/docs/{endpoints,authentication,webhooks} on
2026-09-16 - not yet exercised against a live camerpay.biz account in
this session (see docs/security.md-style disclosure convention: never
claim live validation without actually running it and checking the
result).

Flow: POST /payment/initiate returns a pay_url the customer's browser
must be redirected to; camerpay.biz then POSTs a signed webhook to
CAMERPAY_MERCHANT_CALLBACK_URL when the transaction settles. get_status
calls GET /payment/{uuid}/status for the independent re-check that
app/reconciliation.py always performs before trusting any webhook body.
"""
import hashlib
import hmac
from datetime import datetime

import httpx

from app.core.config import settings
from app.payments.protocol import InitiateResult, PaymentStatus

_STATUS_MAP: dict[str, PaymentStatus] = {
    "pending": "PENDING",
    "processing": "PENDING",
    "completed": "SUCCESSFUL",
    "failed": "FAILED",
    # cancelled/refunded collapse to FAILED: this PaymentStatus/PaymentIntentStatus
    # model has no separate refunded state (refunds are out of baseline scope,
    # see plan.md) - a refund after settlement would need a dedicated flow, not
    # just a status re-check.
    "cancelled": "FAILED",
    "refunded": "FAILED",
}


class CamerPayGateway:
    def __init__(self) -> None:
        self._base_url = settings.camerpay_base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {settings.camerpay_token}",
            "Accept": "application/json",
        }

    async def request_to_pay(self, *, reference: str, amount_xaf: int, payer_msisdn: str) -> InitiateResult:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._base_url}/payment/initiate",
                headers={**self._headers, "Content-Type": "application/json"},
                json={
                    "amount": amount_xaf,
                    "currency": "XAF",
                    "customer_phone": payer_msisdn,
                    "merchant_invoice_id": reference,
                    "merchant_callback_url": settings.camerpay_merchant_callback_url,
                    "merchant_return_url": settings.camerpay_merchant_return_url,
                    "source": "erp",
                    # idempotency_key deliberately omitted: `reference` is
                    # already our own pre-generated, unique-per-intent key,
                    # sent as merchant_invoice_id.
                },
            )
            response.raise_for_status()
            body = response.json()
        return InitiateResult(
            redirect_url=body.get("pay_url"),
            provider_transaction_id=body.get("transaction_uuid"),
        )

    async def get_status(
        self,
        *,
        reference: str,
        requested_at: datetime,
        payer_msisdn: str,
        provider_transaction_id: str | None = None,
    ) -> PaymentStatus:
        if provider_transaction_id is None:
            # request_to_pay's response was never persisted (crash between
            # the HTTP call and the DB write) and no webhook has arrived
            # yet to back-fill it either - nothing to check against yet.
            return "PENDING"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{self._base_url}/payment/{provider_transaction_id}/status",
                headers=self._headers,
            )
            response.raise_for_status()
            provider_status = response.json()["transaction"]["status"]
        return _STATUS_MAP.get(provider_status, "PENDING")


def verify_webhook_signature(*, txn_uuid: str, invoice_id: str, status: str, amount: str, signature: str) -> bool:
    """HMAC-SHA256 hex-lowercase over the pipe-joined 4 fields - NOT the
    raw request body (unlike Stripe/PayPal/GitHub). Verified against the
    official test vector in https://camerpay.biz/docs/webhooks, see
    tests/test_payments.py.
    """
    data = f"{txn_uuid}|{invoice_id}|{status}|{amount}"
    expected = hmac.new(settings.camerpay_callback_secret.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
