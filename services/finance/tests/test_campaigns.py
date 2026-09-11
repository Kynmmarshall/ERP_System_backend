"""Campaign/lead/ROI tests. Require a real, migrated Postgres (see
readme.md)."""
import uuid
from datetime import date

from app.models.finance import InvoiceStatus
from tests.helpers import mint_token, seed_invoice


async def test_roi_is_unavailable_for_zero_cost_campaign(client) -> None:
    institution_id = uuid.uuid4()
    token = mint_token(tenant_id=str(institution_id), role="admin")
    create_resp = await client.post(
        "/api/v1/finance/campaigns",
        json={"name": "Open Day", "cost_xaf": 0, "starts_on": str(date(2026, 1, 1)), "ends_on": str(date(2026, 1, 31))},
        headers={"Authorization": f"Bearer {token}"},
    )
    campaign_id = create_resp.json()["id"]

    response = await client.get(
        f"/api/v1/finance/campaigns/{campaign_id}/roi", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["roi"] is None
    assert body["roi_unavailable_reason"] is not None


async def test_roi_reflects_attributed_revenue_from_converted_leads(client) -> None:
    institution_id = uuid.uuid4()
    token = mint_token(tenant_id=str(institution_id), role="admin")
    create_resp = await client.post(
        "/api/v1/finance/campaigns",
        json={
            "name": "Social Media Push",
            "cost_xaf": 100_000,
            "starts_on": str(date(2026, 1, 1)),
            "ends_on": str(date(2026, 1, 31)),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    campaign_id = create_resp.json()["id"]

    lead_resp = await client.post(
        f"/api/v1/finance/campaigns/{campaign_id}/leads",
        json={"campaign_id": campaign_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    lead_id = lead_resp.json()["id"]

    student_id = uuid.uuid4()
    await seed_invoice(institution_id, student_id, amount_xaf=450_000, status=InvoiceStatus.PAID)

    convert_resp = await client.post(
        f"/api/v1/finance/leads/{lead_id}/convert",
        json={"student_id": str(student_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert convert_resp.json()["status"] == "converted"

    response = await client.get(
        f"/api/v1/finance/campaigns/{campaign_id}/roi", headers={"Authorization": f"Bearer {token}"}
    )

    body = response.json()
    assert body["attributed_revenue_xaf"] == 450_000
    assert body["roi"] == (450_000 - 100_000) / 100_000


async def test_roi_is_negative_full_cost_when_no_leads_convert(client) -> None:
    institution_id = uuid.uuid4()
    token = mint_token(tenant_id=str(institution_id), role="admin")
    create_resp = await client.post(
        "/api/v1/finance/campaigns",
        json={
            "name": "Billboard",
            "cost_xaf": 50_000,
            "starts_on": str(date(2026, 1, 1)),
            "ends_on": str(date(2026, 1, 31)),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    campaign_id = create_resp.json()["id"]

    response = await client.get(
        f"/api/v1/finance/campaigns/{campaign_id}/roi", headers={"Authorization": f"Bearer {token}"}
    )

    body = response.json()
    assert body["attributed_revenue_xaf"] == 0
    assert body["roi"] == -1.0
