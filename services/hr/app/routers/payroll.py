import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_tenant_session, require_roles
from app.models.employees import Employee, EmployeeStatus
from app.models.payroll import PayrollRun, PayrollRunStatus, PayrollScheduleVersion, Payslip
from app.payroll import ScheduleRates, calculate_payslip
from app.schemas import (
    PayrollRunCreateRequest,
    PayrollRunResponse,
    PayrollScheduleCreateRequest,
    PayrollScheduleResponse,
    PayslipResponse,
)

router = APIRouter()

_HR_ADMIN_ROLES = ("admin", "super_admin")
_STAFF_ROLES = ("admin", "lecturer", "finance_staff", "marketing", "super_admin")
_SUPER_ADMIN_ONLY = ("super_admin",)


@router.post("/payroll/schedules", response_model=PayrollScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule_version(
    payload: PayrollScheduleCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> PayrollScheduleVersion:
    """Always created with is_verified=false. There is no automated way to
    "prove" a statutory rate schedule is correct - see
    PATCH /payroll/schedules/{id}/verify for the manual attestation step
    that is the actual release gate.
    """
    schedule = PayrollScheduleVersion(
        institution_id=uuid.UUID(claims["tenant_id"]),
        effective_from=payload.effective_from,
        is_verified=False,
        cnps_employee_rate=payload.cnps_employee_rate,
        cnps_employer_rate=payload.cnps_employer_rate,
        cnps_ceiling_xaf=payload.cnps_ceiling_xaf,
        standard_deduction_rate=payload.standard_deduction_rate,
        irpp_brackets=[bracket.model_dump(mode="json") for bracket in payload.irpp_brackets],
    )
    session.add(schedule)
    await session.commit()
    return schedule


@router.get("/payroll/schedules", response_model=list[PayrollScheduleResponse])
async def list_schedule_versions(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[PayrollScheduleVersion]:
    result = await session.execute(
        select(PayrollScheduleVersion).order_by(PayrollScheduleVersion.effective_from.desc())
    )
    return list(result.scalars().all())


@router.patch("/payroll/schedules/{schedule_id}/verify", response_model=PayrollScheduleResponse)
async def verify_schedule_version(
    schedule_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_SUPER_ADMIN_ONLY)),
    session: AsyncSession = Depends(get_tenant_session),
) -> PayrollScheduleVersion:
    """This endpoint does not itself validate anything - calling it is a
    manual attestation by a super_admin that they have personally checked
    every rate/bracket in this schedule against an authoritative CNPS/DGI
    source for the effective period. Only a verified schedule can back an
    approved (immutable) payroll run - see the payroll run approval
    endpoint below.
    """
    schedule = await session.get(PayrollScheduleVersion, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule version not found")
    schedule.is_verified = True
    await session.commit()
    return schedule


@router.post("/payroll/runs", response_model=PayrollRunResponse, status_code=status.HTTP_201_CREATED)
async def create_payroll_run(
    payload: PayrollRunCreateRequest,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> PayrollRun:
    """Generates a draft run with one payslip per active employee, computed
    via the pure app.payroll.calculate_payslip function. The
    (institution_id, period) unique constraint on payroll_runs makes a
    second call for an already-covered period fail with 409 rather than
    silently double-paying anyone.
    """
    schedule = await session.get(PayrollScheduleVersion, payload.schedule_version_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule version not found")

    run = PayrollRun(
        institution_id=uuid.UUID(claims["tenant_id"]),
        period=payload.period,
        schedule_version_id=schedule.id,
        status=PayrollRunStatus.DRAFT,
    )
    session.add(run)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A run already exists for this period"
        ) from exc

    rates = ScheduleRates(
        cnps_employee_rate=Decimal(schedule.cnps_employee_rate),
        cnps_employer_rate=Decimal(schedule.cnps_employer_rate),
        cnps_ceiling_xaf=schedule.cnps_ceiling_xaf,
        standard_deduction_rate=Decimal(schedule.standard_deduction_rate),
        irpp_brackets=schedule.irpp_brackets,
    )

    employees_result = await session.execute(select(Employee).where(Employee.status == EmployeeStatus.ACTIVE))
    for employee in employees_result.scalars().all():
        breakdown = calculate_payslip(employee.gross_monthly_salary_xaf, rates)
        session.add(
            Payslip(
                institution_id=run.institution_id,
                run_id=run.id,
                employee_id=employee.id,
                period=run.period,
                gross_xaf=breakdown.gross_xaf,
                cnps_employee_xaf=breakdown.cnps_employee_xaf,
                cnps_employer_xaf=breakdown.cnps_employer_xaf,
                taxable_base_xaf=breakdown.taxable_base_xaf,
                irpp_xaf=breakdown.irpp_xaf,
                net_xaf=breakdown.net_xaf,
            )
        )

    await session.commit()
    return run


@router.post("/payroll/runs/{run_id}/approve", response_model=PayrollRunResponse)
async def approve_payroll_run(
    run_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> PayrollRun:
    """The release gate: a run can only be approved if its schedule
    version's is_verified flag is true. This is what prevents an
    unverified/example rate schedule from ever backing a real payroll
    approval.
    """
    run = await session.get(PayrollRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payroll run not found")
    if run.status != PayrollRunStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run already approved")

    schedule = await session.get(PayrollScheduleVersion, run.schedule_version_id)
    if schedule is None or not schedule.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot approve a run backed by an unverified payroll schedule",
        )

    run.status = PayrollRunStatus.APPROVED
    run.approved_by = uuid.UUID(claims["sub"])
    run.approved_at = datetime.now(UTC)
    await session.commit()
    return run


@router.get("/payroll/runs", response_model=list[PayrollRunResponse])
async def list_payroll_runs(
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[PayrollRun]:
    result = await session.execute(select(PayrollRun).order_by(PayrollRun.period.desc()))
    return list(result.scalars().all())


@router.get("/payroll/runs/{run_id}/payslips", response_model=list[PayslipResponse])
async def list_run_payslips(
    run_id: uuid.UUID,
    claims: dict = Depends(require_roles(*_HR_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Payslip]:
    result = await session.execute(select(Payslip).where(Payslip.run_id == run_id))
    return list(result.scalars().all())


@router.get("/payroll/payslips/mine", response_model=list[PayslipResponse])
async def list_my_payslips(
    claims: dict = Depends(require_roles(*_STAFF_ROLES)),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Payslip]:
    """Only shows payslips belonging to APPROVED runs - a draft run's
    figures are not final and must never be shown to the employee.
    """
    employee_result = await session.execute(select(Employee).where(Employee.user_id == uuid.UUID(claims["sub"])))
    employee = employee_result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No employee profile linked to this account")

    result = await session.execute(
        select(Payslip)
        .join(PayrollRun, PayrollRun.id == Payslip.run_id)
        .where(Payslip.employee_id == employee.id, PayrollRun.status == PayrollRunStatus.APPROVED)
        .order_by(Payslip.period.desc())
    )
    return list(result.scalars().all())
