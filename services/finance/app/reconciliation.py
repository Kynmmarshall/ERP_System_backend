import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import set_platform_context
from app.ledger import LedgerLine, post_balanced
from app.models.finance import Invoice, InvoiceStatus
from app.models.ledger import LedgerDirection, LedgerEntryType, Receipt
from app.models.payments import PaymentIntent, PaymentIntentStatus
from app.payments.protocol import PaymentGateway

logger = logging.getLogger("finance.reconciliation")


async def reconcile_intent(
    session: AsyncSession, gateway: PaymentGateway, intent_id: uuid.UUID
) -> PaymentIntentStatus | None:
    """Locks the intent row FOR UPDATE so a concurrent poll tick (or a
    callback-triggered reconcile racing the scheduled poller) can never
    double-process the same intent. Callers must run this inside a
    platform-admin session (see app/payment_worker.py and the callback
    route) since a background/public-endpoint caller has no per-request
    tenant claims to scope RLS with - the intent's own institution_id
    scopes every write instead.
    """
    result = await session.execute(select(PaymentIntent).where(PaymentIntent.id == intent_id).with_for_update())
    intent = result.scalar_one_or_none()
    if intent is None:
        return None
    if intent.status != PaymentIntentStatus.PENDING:
        return intent.status

    provider_status = await gateway.get_status(
        reference=intent.provider_reference, requested_at=intent.created_at, payer_msisdn=intent.payer_msisdn
    )

    if provider_status == "PENDING":
        return PaymentIntentStatus.PENDING

    if provider_status == "FAILED":
        intent.status = PaymentIntentStatus.FAILED
        await session.commit()
        logger.info("Payment intent %s failed", intent.id)
        return PaymentIntentStatus.FAILED

    invoice_result = await session.execute(select(Invoice).where(Invoice.id == intent.invoice_id).with_for_update())
    invoice = invoice_result.scalar_one()
    intent.status = PaymentIntentStatus.SUCCEEDED
    if invoice.status != InvoiceStatus.PAID:
        invoice.status = InvoiceStatus.PAID
        await post_balanced(
            session,
            institution_id=intent.institution_id,
            lines=[
                LedgerLine(LedgerEntryType.CASH, LedgerDirection.DEBIT, intent.amount_xaf, "payment_intent", intent.id),
                LedgerLine(
                    LedgerEntryType.TUITION_REVENUE, LedgerDirection.CREDIT, intent.amount_xaf, "invoice", invoice.id
                ),
            ],
            description=f"Tuition payment for invoice {invoice.id}",
        )
        session.add(
            Receipt(
                institution_id=intent.institution_id,
                invoice_id=invoice.id,
                payment_intent_id=intent.id,
                amount_xaf=intent.amount_xaf,
            )
        )
    await session.commit()
    logger.info("Payment intent %s succeeded, invoice %s paid", intent.id, invoice.id)
    return PaymentIntentStatus.SUCCEEDED


async def reconcile_intent_as_platform_admin(
    session: AsyncSession, gateway: PaymentGateway, intent_id: uuid.UUID
) -> PaymentIntentStatus | None:
    await set_platform_context(session)
    return await reconcile_intent(session, gateway, intent_id)
