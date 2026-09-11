import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractChannel, AbstractQueue, AbstractRobustConnection

from app.core.config import settings

EVENTS_EXCHANGE = "erp.events"
DLX_EXCHANGE = "erp.dlx"
ENROLLMENT_QUEUE = "finance.enrollment_accepted"
ENROLLMENT_DLQ = "finance.enrollment_accepted.dlq"
ENROLLMENT_ROUTING_KEY = "academic.enrollment_accepted.*"


async def connect() -> AbstractRobustConnection:
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def declare_enrollment_queue(channel: AbstractChannel) -> AbstractQueue:
    """Declares the exchange/DLX/DLQ/main-queue topology and returns the main
    queue, already bound. Rejecting a message with requeue=False dead-letters
    it here for visible manual reconciliation instead of a silent retry loop.
    """
    events_exchange = await channel.declare_exchange(EVENTS_EXCHANGE, ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DLX_EXCHANGE, ExchangeType.DIRECT, durable=True)

    dlq = await channel.declare_queue(ENROLLMENT_DLQ, durable=True)
    await dlq.bind(dlx, routing_key=ENROLLMENT_DLQ)

    queue = await channel.declare_queue(
        ENROLLMENT_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": DLX_EXCHANGE,
            "x-dead-letter-routing-key": ENROLLMENT_DLQ,
        },
    )
    await queue.bind(events_exchange, routing_key=ENROLLMENT_ROUTING_KEY)
    return queue
