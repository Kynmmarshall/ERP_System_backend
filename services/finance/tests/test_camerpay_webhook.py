"""Real signature-verification tests for the camerpay.biz webhook route -
see app/payments/camerpay.py and https://camerpay.biz/docs/webhooks.
Require a real, migrated Postgres (see tests/test_payments.py's header).
"""
import hashlib
import hmac
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.payments import PaymentIntent
from app.payments.camerpay import verify_webhook_signature
from tests.helpers import mint_token, seed_invoice

# Official test vector from https://camerpay.biz/docs/webhooks - if this
# ever stops matching, the signing scheme documented there changed.
_TEST_VECTOR_SECRET = "test_secret_key_123"
_TEST_VECTOR_UUID = "5add2319-f71b-4f2d-a4f4-97fe0d11c1d4"
_TEST_VECTOR_INVOICE_ID = "FACT-001"
_TEST_VECTOR_STATUS = "completed"
_TEST_VECTOR_AMOUNT = "10000.00"
_TEST_VECTOR_SIGNATURE = "feab3068de64a00e07ecddc6990570a621eb3d725f9efb728b6a9ca2e455bc37"


def _sign(secret: str, *, txn_uuid: str, invoice_id: str, status: str, amount: str) -> str:
    data = f"{txn_uuid}|{invoice_id}|{status}|{amount}"
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()


def test_signature_matches_official_camerpay_test_vector(monkeypatch) -> None:
    monkeypatch.setattr(settings, "camerpay_callback_secret", _TEST_VECTOR_SECRET)

    assert verify_webhook_signature(
        txn_uuid=_TEST_VECTOR_UUID,
        invoice_id=_TEST_VECTOR_INVOICE_ID,
        status=_TEST_VECTOR_STATUS,
        amount=_TEST_VECTOR_AMOUNT,
        signature=_TEST_VECTOR_SIGNATURE,
    )


def test_signature_rejects_a_tampered_field(monkeypatch) -> None:
    monkeypatch.setattr(settings, "camerpay_callback_secret", _TEST_VECTOR_SECRET)

    assert not verify_webhook_signature(
        txn_uuid=_TEST_VECTOR_UUID,
        invoice_id=_TEST_VECTOR_INVOICE_ID,
        status=_TEST_VECTOR_STATUS,
        amount="99999.00",
        signature=_TEST_VECTOR_SIGNATURE,
    )


async def test_webhook_rejects_invalid_signature(client) -> None:
    response = await client.post(
        "/api/v1/finance/payments/callback/camerpay",
        data={
            "uuid": "does-not-matter",
            "invoice_id": "does-not-matter",
            "status": "completed",
            "amount": "100.00",
            "signature": "0" * 64,
        },
    )

    assert response.status_code == 401


async def test_webhook_with_valid_signature_and_unknown_invoice_id_is_ignored(monkeypatch, client) -> None:
    monkeypatch.setattr(settings, "camerpay_callback_secret", _TEST_VECTOR_SECRET)
    invoice_id = "does-not-exist"
    signature = _sign(
        _TEST_VECTOR_SECRET, txn_uuid=_TEST_VECTOR_UUID, invoice_id=invoice_id, status="completed", amount="100.00"
    )

    response = await client.post(
        "/api/v1/finance/payments/callback/camerpay",
        data={
            "uuid": _TEST_VECTOR_UUID,
            "invoice_id": invoice_id,
            "status": "completed",
            "amount": "100.00",
            "signature": signature,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_webhook_does_not_trust_forged_status_and_backfills_transaction_id(monkeypatch, client) -> None:
    monkeypatch.setattr(settings, "camerpay_callback_secret", _TEST_VECTOR_SECRET)

    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    create_resp = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    provider_reference = create_resp.json()["provider_reference"]

    txn_uuid = str(uuid.uuid4())
    signature = _sign(
        _TEST_VECTOR_SECRET,
        txn_uuid=txn_uuid,
        invoice_id=provider_reference,
        status="completed",
        amount="450000.00",
    )

    callback_resp = await client.post(
        "/api/v1/finance/payments/callback/camerpay",
        data={
            "uuid": txn_uuid,
            "invoice_id": provider_reference,
            "status": "completed",
            "amount": "450000.00",
            "signature": signature,
        },
    )

    assert callback_resp.status_code == 200
    # The test-double gateway still reports PENDING this soon after
    # creation regardless of what the signed webhook body claimed -
    # signature verification proves authenticity, not current truth.
    assert callback_resp.json()["status"] == "pending"

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(
            select(PaymentIntent).where(PaymentIntent.provider_reference == provider_reference)
        )
        intent = result.scalar_one()
        assert intent.provider_transaction_id == txn_uuid
