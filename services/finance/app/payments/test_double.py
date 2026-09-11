"""DISCLOSED deterministic fake for CamerPay/MTN MoMo Collections -
selected via CAMERPAY_PROVIDER=test_double, the default in this dev/CI
environment because no real MTN sandbox credentials are provisioned (see
phase5-plan.md). This is a documented substitute, not a silent mock: it
never claims to have validated anything against the real MTN sandbox.

Stateless by design (no in-memory dict) so it behaves identically whether
called from the finance web process or the separate finance-worker
process polling for status - both only ever have the PaymentIntent row's
`requested_at`/`payer_msisdn` from the database, never a shared Python
object.
"""
from datetime import UTC, datetime, timedelta

from app.payments.protocol import PaymentStatus

SETTLEMENT_DELAY = timedelta(seconds=6)


class CamerPayTestDoubleGateway:
    async def request_to_pay(self, *, reference: str, amount_xaf: int, payer_msisdn: str) -> None:
        """No-op: the real provider call is fire-and-forget too (202
        Accepted then poll), so there is nothing to persist here that
        request_to_pay's caller doesn't already persist itself.
        """
        return None

    async def get_status(self, *, reference: str, requested_at: datetime, payer_msisdn: str) -> PaymentStatus:
        if payer_msisdn.endswith("0000"):
            return "FAILED"
        elapsed = datetime.now(UTC) - requested_at
        return "SUCCESSFUL" if elapsed >= SETTLEMENT_DELAY else "PENDING"
