import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Role(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    LECTURER = "lecturer"
    FINANCE_STAFF = "finance_staff"
    MARKETING = "marketing"
    STUDENT = "student"


class Institution(Base):
    """A tenant. Real deployment starts with one row (ICT University); a
    second row exists only in dev/test fixtures to prove isolation."""

    __tablename__ = "institutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Null only for a platform SUPER_ADMIN acting outside any single tenant.
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_users_institution_id", "institution_id"),)


class RefreshSession(Base):
    """One row per issued refresh token. Rotation replaces the row's hash in
    place is NOT used - instead each rotation inserts a new row sharing
    family_id, and the consumed row is marked revoked, so reuse of a
    stale/rotated-out token is detectable (its row will already be revoked).
    """
    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # institution_id is denormalized from the user at issue time solely so RLS
    # can scope this table the same way as `users` without a join.
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_refresh_sessions_user_id", "user_id"),
        Index("ix_refresh_sessions_family_id", "family_id"),
    )


class MfaChallenge(Base):
    """One row per issued login OTP. The code itself is never stored - only
    its hash, same as refresh tokens - so a database read cannot be replayed
    as a login. Consumed/expired//attempt-exhausted rows are kept rather than
    deleted so a failed-MFA pattern stays visible.
    """

    __tablename__ = "mfa_challenges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized from the user purely so RLS can scope this table the same
    # way as `users`, without a join.
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_mfa_challenges_user_id", "user_id"),)


class RoleRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RoleRequest(Base):
    """A self-registered user's application for a non-student role. The
    account is always created as STUDENT regardless; this row only records
    what they asked for. The elevation happens exclusively when an admin
    approves, so the request itself grants nothing.
    """

    __tablename__ = "role_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalized from the user so RLS can scope this table like `users`.
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=True
    )
    requested_role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"), nullable=False)
    status: Mapped[RoleRequestStatus] = mapped_column(
        Enum(RoleRequestStatus, name="role_request_status"),
        nullable=False,
        default=RoleRequestStatus.PENDING,
    )
    justification: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_role_requests_institution_id", "institution_id"),
        # One open application per user - stops a queue being flooded by
        # repeat submissions from the same account.
        Index(
            "uq_role_requests_one_pending_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )
