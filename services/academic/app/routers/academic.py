import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_claims, get_tenant_session
from app.models.academic import Enrollment, OutboxEvent, Program, Term
from app.schemas import EnrollmentCreateRequest, EnrollmentResponse, ProgramResponse, TermResponse

router = APIRouter()


@router.get("/programs", response_model=list[ProgramResponse])
async def list_programs(session: AsyncSession = Depends(get_tenant_session)) -> list[Program]:
    result = await session.execute(select(Program).order_by(Program.name))
    return list(result.scalars().all())


@router.get("/terms", response_model=list[TermResponse])
async def list_terms(session: AsyncSession = Depends(get_tenant_session)) -> list[Term]:
    result = await session.execute(select(Term).order_by(Term.starts_on))
    return list(result.scalars().all())


@router.post("/enrollments", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    payload: EnrollmentCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Enrollment:
    acting_user_id = uuid.UUID(claims["sub"])
    role = claims.get("role")

    if role == "student":
        student_id = acting_user_id
        if payload.student_id is not None and payload.student_id != acting_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Students may only enroll themselves"
            )
    elif role in ("admin", "lecturer"):
        if payload.student_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="student_id is required")
        student_id = payload.student_id
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")
    institution_id = uuid.UUID(tenant_id)

    # RLS scopes these lookups to the caller's own institution automatically.
    program = await session.get(Program, payload.program_id)
    if program is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program not found")
    term = await session.get(Term, payload.term_id)
    if term is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Term not found")

    existing = await session.execute(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.program_id == program.id,
            Enrollment.term_id == term.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already enrolled")

    enrollment = Enrollment(
        institution_id=institution_id,
        student_id=student_id,
        program_id=program.id,
        term_id=term.id,
    )
    session.add(enrollment)
    await session.flush()

    correlation_id = uuid.uuid4()
    session.add(
        OutboxEvent(
            institution_id=institution_id,
            event_type="academic.enrollment_accepted",
            schema_version=1,
            correlation_id=correlation_id,
            payload={
                "enrollment_id": str(enrollment.id),
                "student_id": str(student_id),
                "program_id": str(program.id),
                "term_id": str(term.id),
            },
        )
    )
    await session.commit()
    return enrollment


@router.get("/enrollments", response_model=list[EnrollmentResponse])
async def list_enrollments(
    claims: dict = Depends(get_current_claims), session: AsyncSession = Depends(get_tenant_session)
) -> list[Enrollment]:
    query = select(Enrollment).order_by(Enrollment.created_at.desc())
    if claims.get("role") == "student":
        query = query.where(Enrollment.student_id == uuid.UUID(claims["sub"]))
    result = await session.execute(query)
    return list(result.scalars().all())
