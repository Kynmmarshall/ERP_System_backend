import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.payments import PaymentIntentStatus
from app.payment_worker import reconcile_pending_intents
from tests.helpers import seed_invoice, seed_pending_intent


async def test_reconcile_pending_intents_settles_a_ready_intent() -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    intent = await seed_pending_intent(
        institution_id, invoice, payer_msisdn="670000001", requested_at=datetime.now(UTC) - timedelta(seconds=30)
    )

    reconciled_count = await reconcile_pending_intents()

    assert reconciled_count >= 1

    async with SessionFactory() as session:
        await set_platform_context(session)
        refreshed = await session.get(type(intent), intent.id)
        assert refreshed.status == PaymentIntentStatus.SUCCEEDED
