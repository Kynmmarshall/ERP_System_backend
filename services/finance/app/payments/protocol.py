from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

PaymentStatus = Literal["PENDING", "SUCCESSFUL", "FAILED"]


@dataclass
class InitiateResult:
    """redirect_url is set by hosted-checkout providers (camerpay) so the
    caller can send the customer's browser there; direct push-to-phone
    providers (mtn_momo, test_double) leave it None. provider_transaction_id
    is the provider's OWN id for the transaction (distinct from our
    pre-generated `reference`/idempotency key) - only camerpay needs it, to
    later call GET /payment/{uuid}/status for reconciliation.
    """

    redirect_url: str | None = None
    provider_transaction_id: str | None = None


class PaymentGateway(Protocol):
    """Every gateway (real MTN MoMo, the real camerpay.biz aggregator, and
    the disclosed test double) implements this shape so swapping between
    them is a config change (CAMERPAY_PROVIDER), never a code change.
    get_status takes requested_at and payer_msisdn (not just reference) so
    a stateless test double can derive a deterministic status without any
    in-memory state shared across the web and worker processes; MTN
    ignores them and calls GET .../requesttopay/{referenceId}. camerpay
    ignores requested_at/payer_msisdn too but needs provider_transaction_id
    (persisted from InitiateResult, or backed-filled from a verified
    webhook body) to call GET /payment/{uuid}/status.
    """

    async def request_to_pay(self, *, reference: str, amount_xaf: int, payer_msisdn: str) -> InitiateResult: ...

    async def get_status(
        self,
        *,
        reference: str,
        requested_at: datetime,
        payer_msisdn: str,
        provider_transaction_id: str | None = None,
    ) -> PaymentStatus: ...
