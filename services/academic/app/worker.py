"""Outbox publisher: polls unpublished rows and publishes them, one small
batch at a time, with publisher confirms so a broker outage never silently
loses an event - the row simply stays unpublished until the next poll.

Run as its own process/container (see docker-compose.yml `academic-worker`),
sharing the same image and database as the web process.
"""
import asyncio
import json
import logging
from datetime import UTC, datetime

import aio_pika
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.rabbitmq import connect, declare_events_exchange
from app.models.academic import OutboxEvent

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("academic.worker")

POLL_INTERVAL_SECONDS = 2
BATCH_SIZE = 20


def _build_envelope(event: OutboxEvent) -> dict:
    return {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "tenant_id": str(event.institution_id),
        "occurred_at": event.created_at.astimezone(UTC).isoformat(),
        "correlation_id": str(event.correlation_id),
        "data": event.payload,
    }


def _routing_key(event: OutboxEvent) -> str:
    """RabbitMQ routing key is the versioned form (e.g. `...accepted.v1`);
    the envelope's own `event_type` field stays unversioned per the contract
    schema, with `schema_version` as the separate version field.
    """
    return f"{event.event_type}.v{event.schema_version}"


async def publish_pending_events(exchange: aio_pika.abc.AbstractExchange) -> int:
    published = 0
    async with SessionFactory() as session:
        async with session.begin():
            result = await session.execute(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            pending = result.scalars().all()
            for event in pending:
                envelope = _build_envelope(event)
                await exchange.publish(
                    aio_pika.Message(
                        body=json.dumps(envelope).encode("utf-8"),
                        message_id=str(event.id),
                        content_type="application/json",
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    ),
                    routing_key=_routing_key(event),
                )
                event.published_at = datetime.now(UTC)
                published += 1
    return published


async def run_forever() -> None:
    connection = await connect()
    async with connection:
        channel = await connection.channel(publisher_confirms=True)
        exchange = await declare_events_exchange(channel)
        logger.info("Outbox publisher started, polling every %ss", POLL_INTERVAL_SECONDS)
        while True:
            try:
                count = await publish_pending_events(exchange)
                if count:
                    logger.info("Published %d outbox event(s)", count)
            except Exception:
                logger.exception("Outbox publish cycle failed; will retry")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_forever())
