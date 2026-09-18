import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.assets import Asset, AssetMovement
from app.schemas import AssetCreateRequest, AssetMovementCreateRequest, AssetMovementResponse, AssetResponse

router = APIRouter()

_HR_ADMIN_ROLES = ("admin",)


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    payload: AssetCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> Asset:
    asset = Asset(
        institution_id=uuid.UUID(claims["tenant_id"]),
        name=payload.name,
        category=payload.category,
        total_quantity=payload.total_quantity,
    )
    session.add(asset)
    await session.commit()
    return asset


@router.get("/assets", response_model=list[AssetResponse])
async def list_assets(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Asset]:
    result = await session.execute(select(Asset).order_by(Asset.created_at.desc()))
    return list(result.scalars().all())


@router.post("/assets/movements", response_model=AssetMovementResponse, status_code=status.HTTP_201_CREATED)
async def create_asset_movement(
    payload: AssetMovementCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> AssetMovement:
    """quantity_delta convention (see app/models/assets.py):
    - employee_id set: change in quantity assigned out to that employee.
      Positive = assigning units to them (on-hand decreases); negative =
      that employee returning units to stock (on-hand increases).
    - employee_id null: a direct general-stock adjustment (write-off,
      found item, correction) that changes total_quantity directly and
      does not affect any employee's assigned quantity.
    Both branches are evaluated after locking the asset row FOR UPDATE so
    concurrent movements against the same asset serialize and on-hand
    stock can never be driven negative.
    """
    result = await session.execute(select(Asset).where(Asset.id == payload.asset_id).with_for_update())
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    assigned_out_result = await session.execute(
        select(func.coalesce(func.sum(AssetMovement.quantity_delta), 0)).where(
            AssetMovement.asset_id == asset.id, AssetMovement.employee_id.is_not(None)
        )
    )
    assigned_out = assigned_out_result.scalar_one()

    if payload.employee_id is not None:
        new_assigned_out = assigned_out + payload.quantity_delta
        if new_assigned_out < 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Return exceeds assigned quantity")
        if new_assigned_out > asset.total_quantity:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Insufficient on-hand stock")
    else:
        new_total = asset.total_quantity + payload.quantity_delta
        if new_total < 0 or new_total < assigned_out:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Adjustment would drive stock below assigned quantity"
            )
        asset.total_quantity = new_total

    movement = AssetMovement(
        institution_id=uuid.UUID(claims["tenant_id"]),
        asset_id=asset.id,
        employee_id=payload.employee_id,
        quantity_delta=payload.quantity_delta,
        reason=payload.reason,
    )
    session.add(movement)
    await session.commit()
    return movement


@router.get("/assets/{asset_id}/movements", response_model=list[AssetMovementResponse])
async def list_asset_movements(
    asset_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AssetMovement]:
    result = await session.execute(
        select(AssetMovement).where(AssetMovement.asset_id == asset_id).order_by(AssetMovement.created_at.desc())
    )
    return list(result.scalars().all())
