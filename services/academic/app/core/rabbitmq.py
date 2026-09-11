import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractExchange, AbstractRobustConnection

from app.core.config import settings

EVENTS_EXCHANGE = "erp.events"


async def connect() -> AbstractRobustConnection:
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def declare_events_exchange(channel: aio_pika.abc.AbstractChannel) -> AbstractExchange:
    return await channel.declare_exchange(EVENTS_EXCHANGE, ExchangeType.TOPIC, durable=True)
