"""Reconciliation tests: succeeded intents post a balanced ledger entry,
create exactly one receipt, and mark the invoice paid - all in one
transaction. Requires a real, migrated Postgres (see readme.md).
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.finance import Invoice, InvoiceStatus
from app.models.ledger import LedgerDirection, LedgerEntry, Receipt
from app.models.payments import PaymentIntentStatus
from app.payments.test_double import CamerPayTestDoubleGateway
from app.reconciliation import reconcile_intent
from tests.helpers import seed_invoice, seed_pending_intent


async def test_successful_reconciliation_posts_balanced_ledger_and_one_receipt() -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id, amount_xaf=450_000)
    intent = await seed_pending_intent(
        institution_id, invoice, payer_msisdn="670000001", requested_at=datetime.now(UTC) - timedelta(seconds=30)
    )

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await reconcile_intent(session, CamerPayTestDoubleGateway(), intent.id)
        assert result == PaymentIntentStatus.SUCCEEDED

    async with SessionFactory() as session:
        await set_platform_context(session)
        invoice_row = await session.get(Invoice, invoice.id)
        assert invoice_row.status == InvoiceStatus.PAID

        receipts = (await session.execute(select(Receipt).where(Receipt.invoice_id == invoice.id))).scalars().all()
        assert len(receipts) == 1
        assert receipts[0].amount_xaf == 450_000

        entries = (
            (await session.execute(select(LedgerEntry).where(LedgerEntry.reference_id == invoice.id))).scalars().all()
        )
        credit_entries = [e for e in entries if e.direction == LedgerDirection.CREDIT]
        assert sum(e.amount_xaf for e in credit_entries) == 450_000
        debit_entries = (
            (
                await session.execute(
                    select(LedgerEntry).where(
                        LedgerEntry.reference_id == intent.id, LedgerEntry.direction == LedgerDirection.DEBIT
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sum(e.amount_xaf for e in debit_entries) == 450_000
        assert debit_entries[0].posting_id == credit_entries[0].posting_id


async def test_failed_reconciliation_marks_intent_failed_without_touching_invoice() -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    intent = await seed_pending_intent(
        institution_id, invoice, payer_msisdn="670000000", requested_at=datetime.now(UTC)
    )

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await reconcile_intent(session, CamerPayTestDoubleGateway(), intent.id)
        assert result == PaymentIntentStatus.FAILED

    async with SessionFactory() as session:
        await set_platform_context(session)
        invoice_row = await session.get(Invoice, invoice.id)
        assert invoice_row.status == InvoiceStatus.PENDING


async def test_reconciling_an_already_succeeded_intent_is_a_no_op() -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id, amount_xaf=450_000)
    intent = await seed_pending_intent(
        institution_id, invoice, payer_msisdn="670000001", requested_at=datetime.now(UTC) - timedelta(seconds=30)
    )
    gateway = CamerPayTestDoubleGateway()

    async with SessionFactory() as session:
        await set_platform_context(session)
        await reconcile_intent(session, gateway, intent.id)

    async with SessionFactory() as session:
        await set_platform_context(session)
        second_result = await reconcile_intent(session, gateway, intent.id)
        assert second_result == PaymentIntentStatus.SUCCEEDED

    async with SessionFactory() as session:
        await set_platform_context(session)
        receipts = (await session.execute(select(Receipt).where(Receipt.invoice_id == invoice.id))).scalars().all()
        assert len(receipts) == 1
