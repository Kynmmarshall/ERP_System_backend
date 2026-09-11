from datetime import datetime
from typing import Literal, Protocol

PaymentStatus = Literal["PENDING", "SUCCESSFUL", "FAILED"]


class PaymentGateway(Protocol):
    """Both the real MTN MoMo gateway and the disclosed test double
    implement this shape so swapping between them is a config change
    (CAMERPAY_PROVIDER), never a code change. get_status takes requested_at
    and payer_msisdn (not just reference) so a stateless test double can
    derive a deterministic status without any in-memory state shared
    across the web and worker processes; the real gateway simply ignores
    them and calls MTN's GET .../requesttopay/{referenceId}.
    """

    async def request_to_pay(self, *, reference: str, amount_xaf: int, payer_msisdn: str) -> None: ...

    async def get_status(self, *, reference: str, requested_at: datetime, payer_msisdn: str) -> PaymentStatus: ...
