"""Direct unit tests of the disclosed CamerPay test double - no DB or API
involved, pure gateway logic.
"""
from datetime import UTC, datetime, timedelta

from app.payments.test_double import SETTLEMENT_DELAY, CamerPayTestDoubleGateway


async def test_status_is_pending_before_settlement_delay_elapses() -> None:
    gateway = CamerPayTestDoubleGateway()
    status = await gateway.get_status(
        reference="ref-1", requested_at=datetime.now(UTC), payer_msisdn="670000001"
    )
    assert status == "PENDING"


async def test_status_is_successful_after_settlement_delay_elapses() -> None:
    gateway = CamerPayTestDoubleGateway()
    status = await gateway.get_status(
        reference="ref-1",
        requested_at=datetime.now(UTC) - SETTLEMENT_DELAY - timedelta(seconds=1),
        payer_msisdn="670000001",
    )
    assert status == "SUCCESSFUL"


async def test_msisdn_ending_0000_always_fails() -> None:
    gateway = CamerPayTestDoubleGateway()
    status = await gateway.get_status(
        reference="ref-1",
        requested_at=datetime.now(UTC) - SETTLEMENT_DELAY - timedelta(seconds=1),
        payer_msisdn="670000000",
    )
    assert status == "FAILED"
