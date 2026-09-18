import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.marketing import Campaign, Lead, LeadStatus
from app.schemas import (
    CampaignCreateRequest,
    CampaignResponse,
    CampaignRoiResponse,
    LeadConvertRequest,
    LeadCreateRequest,
    LeadResponse,
)

router = APIRouter()

# Campaigns, leads and ROI belong to marketing, not to the finance desk.
_STAFF_ROLES = ("admin", "marketing")


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Campaign:
    campaign = Campaign(
        institution_id=uuid.UUID(claims["tenant_id"]),
        name=payload.name,
        cost_xaf=payload.cost_xaf,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
    )
    session.add(campaign)
    await session.commit()
    return campaign


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Campaign]:
    result = await session.execute(select(Campaign).order_by(Campaign.starts_on.desc()))
    return list(result.scalars().all())


@router.post("/campaigns/{campaign_id}/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    campaign_id: uuid.UUID,
    payload: LeadCreateRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Lead:
    if payload.campaign_id != campaign_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="campaign_id mismatch")
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    lead = Lead(institution_id=campaign.institution_id, campaign_id=campaign.id)
    session.add(lead)
    await session.commit()
    return lead


@router.get("/campaigns/{campaign_id}/leads", response_model=list[LeadResponse])
async def list_leads(
    campaign_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Lead]:
    result = await session.execute(select(Lead).where(Lead.campaign_id == campaign_id))
    return list(result.scalars().all())


@router.post("/leads/{lead_id}/convert", response_model=LeadResponse)
async def convert_lead(
    lead_id: uuid.UUID,
    payload: LeadConvertRequest,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Lead:
    lead = await session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    lead.status = LeadStatus.CONVERTED
    lead.student_id = payload.student_id
    await session.commit()
    return lead


@router.get("/campaigns/{campaign_id}/roi", response_model=CampaignRoiResponse)
async def campaign_roi(
    campaign_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> CampaignRoiResponse:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    result = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(i.amount_xaf), 0) AS attributed_revenue
            FROM leads l
            JOIN invoices i ON i.student_id = l.student_id AND i.status = 'PAID'
            WHERE l.campaign_id = :campaign_id AND l.status = 'CONVERTED'
            """
        ),
        {"campaign_id": str(campaign_id)},
    )
    attributed_revenue = result.scalar_one()

    if campaign.cost_xaf > 0:
        roi = (attributed_revenue - campaign.cost_xaf) / campaign.cost_xaf
        roi_unavailable_reason = None
    else:
        roi = None
        roi_unavailable_reason = "Campaign has zero recorded cost"

    return CampaignRoiResponse(
        campaign_id=campaign_id,
        cost_xaf=campaign.cost_xaf,
        attributed_revenue_xaf=attributed_revenue,
        roi=roi,
        roi_unavailable_reason=roi_unavailable_reason,
    )
