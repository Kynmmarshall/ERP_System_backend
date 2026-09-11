"""PaymentIntent creation/status tests. Require a real, migrated Postgres
reachable via DATABASE_URL (see readme.md) - these exercise real RLS, the
partial unique index and the reconciliation path, not a mocked DB layer.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.db import SessionFactory
from app.core.tenant_context import set_platform_context
from app.models.finance import InvoiceStatus
from app.models.payments import PaymentIntent
from tests.helpers import mint_token, seed_invoice


async def test_creating_intent_persists_before_any_gateway_call_could_fail(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["invoice_id"] == str(invoice.id)

    async with SessionFactory() as session:
        await set_platform_context(session)
        result = await session.execute(select(PaymentIntent).where(PaymentIntent.id == uuid.UUID(body["id"])))
        assert result.scalar_one() is not None


async def test_second_intent_while_one_is_active_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")
    payload = {"payer_msisdn": "670000001"}

    first = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409


async def test_new_intent_allowed_after_a_prior_one_failed(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    # msisdn ending 0000 is the test double's deterministic FAILED case.
    first = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    first_id = first.json()["id"]

    status_response = await client.get(
        f"/api/v1/finance/payment-intents/{first_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert status_response.json()["status"] == "failed"

    second = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 201


async def test_get_intent_reconciles_to_succeeded_once_settlement_delay_elapses(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    create_resp = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    intent_id = uuid.UUID(create_resp.json()["id"])

    async with SessionFactory() as session:
        await set_platform_context(session)
        await session.execute(
            update(PaymentIntent)
            .where(PaymentIntent.id == intent_id)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=30))
        )
        await session.commit()

    response = await client.get(
        f"/api/v1/finance/payment-intents/{intent_id}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.json()["status"] == "succeeded"


async def test_student_cannot_pay_someone_elses_invoice(client) -> None:
    institution_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, uuid.uuid4())
    token = mint_token(tenant_id=str(institution_id), role="student")

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_payment_intent_on_unknown_invoice_is_rejected(client) -> None:
    token = mint_token(role="student")

    response = await client.post(
        f"/api/v1/finance/invoices/{uuid.uuid4()}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


async def test_payment_intent_on_already_paid_invoice_is_rejected(client) -> None:
    institution_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = await seed_invoice(institution_id, student_id, status=InvoiceStatus.PAID)
    token = mint_token(sub=str(student_id), tenant_id=str(institution_id), role="student")

    response = await client.post(
        f"/api/v1/finance/invoices/{invoice.id}/payment-intents",
        json={"payer_msisdn": "670000001"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


async def test_get_unknown_payment_intent_is_rejected(client) -> None:
    token = mint_token(role="student")

    response = await client.get(
        f"/api/v1/finance/payment-intents/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404


async def test_callback_with_unknown_reference_is_ignored(client) -> None:
    response = await client.post("/api/v1/finance/payments/callback", json={"reference": "does-not-exist"})

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


async def test_callback_does_not_trust_forged_status_body(client) -> None:
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

    callback_resp = await client.post(
        "/api/v1/finance/payments/callback",
        json={"reference": provider_reference, "status": "SUCCESSFUL"},
    )
    assert callback_resp.status_code == 200
    # The test-double gateway still reports PENDING this soon after
    # creation regardless of what the forged callback body claimed.
    assert callback_resp.json()["status"] == "pending"
