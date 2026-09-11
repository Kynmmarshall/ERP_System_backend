"""Receipt PDF tests. Require a real, migrated Postgres (see readme.md)."""
import uuid
from datetime import UTC, datetime, timedelta

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.payments.test_double import CamerPayTestDoubleGateway
from app.reconciliation import reconcile_intent
from tests.helpers import mint_token, seed_invoice, seed_pending_intent


async def test_receipt_pdf_is_returned_after_successful_payment(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id, amount_xaf=450_000)
    intent = await seed_pending_intent(
        institution_id, invoice, payer_msisdn="670000001", requested_at=datetime.now(UTC) - timedelta(seconds=30)
    )
    async with SessionFactory() as session:
        await set_platform_context(session)
        await reconcile_intent(session, CamerPayTestDoubleGateway(), intent.id)

    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    response = await client.get(
        f"/api/v1/finance/invoices/{invoice.id}/receipt", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_receipt_not_found_before_payment_succeeds(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.get(
        f"/api/v1/finance/invoices/{invoice.id}/receipt", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404
