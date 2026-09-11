"""Shared test helpers for Phase 5 finance tests - see academic's
tests/helpers.py for the same pattern."""
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

from app.core.db import SessionFactory
from app.core.security import JWT_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER
from app.core.tenant_context import set_platform_context
from app.models.finance import Invoice, InvoiceStatus
from app.models.payments import PaymentIntent


def private_key() -> str:
    path = os.environ["JWT_PRIVATE_KEY_PATH_FOR_TESTS"]
    return Path(path).read_text(encoding="utf-8")


def mint_token(*, expires_delta: timedelta = timedelta(minutes=10), **overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "campus_id": None,
        "role": "student",
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key(), algorithm=JWT_ALGORITHM)


async def seed_invoice(
    institution_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    amount_xaf: int = 450_000,
    status: InvoiceStatus = InvoiceStatus.PENDING,
) -> Invoice:
    async with SessionFactory() as session:
        await set_platform_context(session)
        invoice = Invoice(
            institution_id=institution_id,
            enrollment_id=uuid.uuid4(),
            student_id=student_id,
            amount_xaf=amount_xaf,
            status=status,
        )
        session.add(invoice)
        await session.commit()
        return invoice


async def seed_pending_intent(
    institution_id: uuid.UUID, invoice: Invoice, *, payer_msisdn: str, requested_at: datetime
) -> PaymentIntent:
    async with SessionFactory() as session:
        await set_platform_context(session)
        intent = PaymentIntent(
            institution_id=institution_id,
            invoice_id=invoice.id,
            amount_xaf=invoice.amount_xaf,
            provider="mtn_momo",
            provider_reference=str(uuid.uuid4()),
            payer_msisdn=payer_msisdn,
            created_at=requested_at,
        )
        session.add(intent)
        await session.commit()
        return intent
