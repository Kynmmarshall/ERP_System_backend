import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_assets_institution_id", "institution_id"),
        CheckConstraint("total_quantity >= 0", name="ck_assets_total_quantity_nonnegative"),
    )


class AssetMovement(Base):
    """quantity_delta convention: when employee_id is set, this is the
    change in quantity assigned out to that employee (positive =
    assigning units to them, negative = them returning units to stock).
    When employee_id is null, this is a direct general-stock adjustment
    (write-off, found item, correction) applied straight to the asset's
    total_quantity. Outstanding assigned-out quantity for an asset is
    always SUM(quantity_delta) among movements with a non-null
    employee_id. A movement that would drive on-hand stock (total_quantity
    minus assigned-out) negative is rejected inside a row-locked
    transaction (see app/routers/assets.py), not just checked
    optimistically.
    """

    __tablename__ = "asset_movements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_asset_movements_institution_id", "institution_id"),
        Index("ix_asset_movements_asset_id", "asset_id"),
    )
