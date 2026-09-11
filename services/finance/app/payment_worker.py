import asyncio
import logging

from sqlalchemy import select

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.payments import PaymentIntent, PaymentIntentStatus
from app.payments import get_gateway
from app.reconciliation import reconcile_intent
from app.summaries import run_catch_up

logger = logging.getLogger("finance.payment_worker")

RECONCILE_POLL_INTERVAL_SECONDS = 3
SUMMARY_CATCH_UP_INTERVAL_SECONDS = 3600


async def reconcile_pending_intents() -> int:
    gateway = get_gateway()
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(PaymentIntent.id).where(PaymentIntent.status == PaymentIntentStatus.PENDING)
        )
        pending_ids = [row[0] for row in result.all()]

    reconciled = 0
    for intent_id in pending_ids:
        async with SessionFactory() as session:
            await set_platform_context(session)
            new_status = await reconcile_intent(session, gateway, intent_id)
            if new_status is not None and new_status != PaymentIntentStatus.PENDING:
                reconciled += 1
    return reconciled


async def run_payment_reconciliation_loop() -> None:
    while True:
        try:
            count = await reconcile_pending_intents()
            if count:
                logger.info("Reconciled %d payment intent(s)", count)
        except Exception:
            logger.exception("Payment reconciliation tick failed; will retry")
        await asyncio.sleep(RECONCILE_POLL_INTERVAL_SECONDS)


async def run_summary_catch_up_loop() -> None:
    while True:
        try:
            async with SessionFactory() as session:
                await set_platform_context(session)
                created = await run_catch_up(session)
                if created:
                    logger.info("Generated %d catch-up financial summary/ies", created)
        except Exception:
            logger.exception("Summary catch-up tick failed; will retry")
        await asyncio.sleep(SUMMARY_CATCH_UP_INTERVAL_SECONDS)
