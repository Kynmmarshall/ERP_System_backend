"""Consumes EnrollmentAccepted.v1 and creates exactly one invoice per
enrollment, or leaves the message on the DLQ for visible manual
reconciliation - it never guesses a price. Run as its own process/container
(see docker-compose.yml `finance-worker`).
"""
import asyncio
import json
import logging
import uuid

from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.rabbitmq import connect, declare_enrollment_queue
from app.core.tenant_context import set_platform_context
from app.models.finance import FeeSchedule, InboxEvent, Invoice
from app.payment_worker import run_payment_reconciliation_loop, run_summary_catch_up_loop

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("finance.consumer")

PREFETCH_COUNT = 10


async def _find_fee_schedule(
    session: AsyncSession, *, institution_id: uuid.UUID, program_id: uuid.UUID, term_id: uuid.UUID
) -> FeeSchedule | None:
    result = await session.execute(
        select(FeeSchedule).where(
            FeeSchedule.institution_id == institution_id,
            FeeSchedule.program_id == program_id,
            FeeSchedule.term_id == term_id,
        )
    )
    return result.scalar_one_or_none()


async def handle_message(message: AbstractIncomingMessage) -> None:
    try:
        envelope = json.loads(message.body)
    except json.JSONDecodeError:
        logger.error("Malformed event payload, dead-lettering: %s", message.body[:200])
        await message.reject(requeue=False)
        return

    try:
        event_id = uuid.UUID(envelope["event_id"])
        event_type = envelope["event_type"]
        institution_id = uuid.UUID(envelope["tenant_id"])
        data = envelope["data"]
        enrollment_id = uuid.UUID(data["enrollment_id"])
        student_id = uuid.UUID(data["student_id"])
        program_id = uuid.UUID(data["program_id"])
        term_id = uuid.UUID(data["term_id"])
    except (KeyError, ValueError, TypeError):
        logger.error("Event failed contract validation, dead-lettering: %s", envelope)
        await message.reject(requeue=False)
        return

    try:
        async with SessionFactory() as session:
            async with session.begin():
                # This is a trusted internal process that must read/write
                # fee_schedules and invoices across every tenant in the same
                # run - there is no single per-request institution to scope
                # to, so it deliberately runs with RLS bypassed (like the
                # outbox worker/seed scripts), and instead relies on the
                # institution_id taken from the verified envelope for every
                # row it writes.
                await set_platform_context(session)
                session.add(InboxEvent(event_id=event_id, event_type=event_type))
                try:
                    await session.flush()
                except IntegrityError:
                    # Already processed (redelivery/duplicate) - a no-op success.
                    await session.rollback()
                    await message.ack()
                    return

                fee_schedule = await _find_fee_schedule(
                    session, institution_id=institution_id, program_id=program_id, term_id=term_id
                )
                if fee_schedule is None:
                    # Visible reconciliation work, never a guessed/zero invoice.
                    logger.warning(
                        "No fee schedule for institution=%s program=%s term=%s; dead-lettering enrollment=%s",
                        institution_id,
                        program_id,
                        term_id,
                        enrollment_id,
                    )
                    await session.rollback()
                    await message.reject(requeue=False)
                    return

                try:
                    session.add(
                        Invoice(
                            institution_id=institution_id,
                            enrollment_id=enrollment_id,
                            student_id=student_id,
                            amount_xaf=fee_schedule.amount_xaf,
                        )
                    )
                    await session.flush()
                except IntegrityError:
                    # Same enrollment already invoiced under a different event_id.
                    await session.rollback()
                    await message.ack()
                    return
        await message.ack()
        logger.info("Invoiced enrollment=%s amount_xaf=%s", enrollment_id, fee_schedule.amount_xaf)
    except Exception:
        logger.exception("Transient failure processing enrollment event; requeueing")
        await message.nack(requeue=True)


async def run_forever() -> None:
    connection = await connect()
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=PREFETCH_COUNT)
        queue = await declare_enrollment_queue(channel)
        logger.info("Finance consumer started, listening on %s", queue.name)
        await queue.consume(handle_message)
        # Payment reconciliation and monthly-summary catch-up run as
        # concurrent tasks in this same worker process rather than as
        # separate containers - see phase5-plan.md.
        await asyncio.gather(
            asyncio.Future(),
            run_payment_reconciliation_loop(),
            run_summary_catch_up_loop(),
        )


if __name__ == "__main__":
    asyncio.run(run_forever())
