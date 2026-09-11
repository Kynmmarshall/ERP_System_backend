"""Consumer idempotency/dead-lettering tests. Call handle_message directly
with a fake AbstractIncomingMessage instead of a real RabbitMQ broker - the
queue/exchange topology itself has no conditional logic worth testing here,
only handle_message's transaction/idempotency behaviour does. Require a real,
migrated Postgres reachable via DATABASE_URL (see readme.md).
"""
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.consumer import handle_message
from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.finance import FeeSchedule, Invoice


class FakeIncomingMessage:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.acked = False
        self.rejected: bool | None = None
        self.nacked: bool | None = None

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool) -> None:
        self.rejected = requeue

    async def nack(self, requeue: bool) -> None:
        self.nacked = requeue


def _make_envelope(*, institution_id: uuid.UUID, program_id: uuid.UUID, term_id: uuid.UUID, **data_overrides) -> dict:
    data = {
        "enrollment_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "program_id": str(program_id),
        "term_id": str(term_id),
        "campus_id": str(uuid.uuid4()),
    }
    data.update(data_overrides)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "academic.enrollment_accepted",
        "schema_version": 1,
        "tenant_id": str(institution_id),
        "occurred_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
        "data": data,
    }


async def _seed_fee_schedule(
    *, institution_id: uuid.UUID, program_id: uuid.UUID, term_id: uuid.UUID, amount_xaf: int
) -> None:
    async with SessionFactory() as session:
        await set_platform_context(session)
        session.add(
            FeeSchedule(institution_id=institution_id, program_id=program_id, term_id=term_id, amount_xaf=amount_xaf)
        )
        await session.commit()


async def _count_invoices(enrollment_id: uuid.UUID) -> int:
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(Invoice).where(Invoice.enrollment_id == enrollment_id))
        return len(result.scalars().all())


async def test_valid_event_creates_exactly_one_invoice_with_scheduled_amount() -> None:
    institution_id = uuid.uuid4()
    program_id = uuid.uuid4()
    term_id = uuid.uuid4()
    await _seed_fee_schedule(institution_id=institution_id, program_id=program_id, term_id=term_id, amount_xaf=450_000)
    envelope = _make_envelope(institution_id=institution_id, program_id=program_id, term_id=term_id)
    enrollment_id = uuid.UUID(envelope["data"]["enrollment_id"])
    message = FakeIncomingMessage(json.dumps(envelope).encode("utf-8"))

    await handle_message(message)

    assert message.acked is True
    assert await _count_invoices(enrollment_id) == 1
    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(Invoice).where(Invoice.enrollment_id == enrollment_id))
        invoice = result.scalar_one()
        assert invoice.amount_xaf == 450_000
        assert invoice.status.value == "pending"


async def test_duplicate_event_id_is_idempotent() -> None:
    institution_id = uuid.uuid4()
    program_id = uuid.uuid4()
    term_id = uuid.uuid4()
    await _seed_fee_schedule(institution_id=institution_id, program_id=program_id, term_id=term_id, amount_xaf=450_000)
    envelope = _make_envelope(institution_id=institution_id, program_id=program_id, term_id=term_id)
    enrollment_id = uuid.UUID(envelope["data"]["enrollment_id"])
    body = json.dumps(envelope).encode("utf-8")

    first = FakeIncomingMessage(body)
    await handle_message(first)
    second = FakeIncomingMessage(body)
    await handle_message(second)

    assert first.acked is True
    assert second.acked is True
    assert await _count_invoices(enrollment_id) == 1


async def test_missing_fee_schedule_is_dead_lettered_without_creating_invoice() -> None:
    envelope = _make_envelope(institution_id=uuid.uuid4(), program_id=uuid.uuid4(), term_id=uuid.uuid4())
    enrollment_id = uuid.UUID(envelope["data"]["enrollment_id"])
    message = FakeIncomingMessage(json.dumps(envelope).encode("utf-8"))

    await handle_message(message)

    assert message.rejected is False
    assert message.acked is False
    assert await _count_invoices(enrollment_id) == 0


async def test_malformed_json_is_dead_lettered() -> None:
    message = FakeIncomingMessage(b"not valid json")

    await handle_message(message)

    assert message.rejected is False
    assert message.acked is False


async def test_event_missing_required_field_is_dead_lettered() -> None:
    envelope = _make_envelope(institution_id=uuid.uuid4(), program_id=uuid.uuid4(), term_id=uuid.uuid4())
    del envelope["data"]["student_id"]
    message = FakeIncomingMessage(json.dumps(envelope).encode("utf-8"))

    await handle_message(message)

    assert message.rejected is False
    assert message.acked is False
