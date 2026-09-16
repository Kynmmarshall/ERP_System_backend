import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import ensure_can_manage_offering
from app.deps import get_current_claims, get_tenant_session
from app.models.courses import CourseOffering
from app.models.grades import AppealStatus, Assessment, Grade, GradeAppeal, GradeAuditLog
from app.schemas import (
    AssessmentCreateRequest,
    AssessmentResponse,
    GradeAppealCreateRequest,
    GradeAppealDecisionRequest,
    GradeAppealResponse,
    GradeEntryRequest,
    GradeResponse,
)

router = APIRouter()

_STAFF_ROLES = ("admin", "lecturer", "super_admin")


async def _get_offering_or_404(session: AsyncSession, course_offering_id: uuid.UUID) -> CourseOffering:
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    return offering


@router.post("/assessments", response_model=AssessmentResponse, status_code=status.HTTP_201_CREATED)
async def create_assessment(
    payload: AssessmentCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Assessment:
    tenant_id = claims.get("tenant_id")
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No institution context")
    offering = await _get_offering_or_404(session, payload.course_offering_id)
    ensure_can_manage_offering(offering, claims)

    assessment = Assessment(
        institution_id=uuid.UUID(tenant_id),
        course_offering_id=payload.course_offering_id,
        name=payload.name,
        max_score=payload.max_score,
    )
    session.add(assessment)
    await session.commit()
    return assessment


@router.get("/assessments", response_model=list[AssessmentResponse])
async def list_assessments(
    course_offering_id: uuid.UUID = Query(...),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Assessment]:
    result = await session.execute(
        select(Assessment)
        .where(Assessment.course_offering_id == course_offering_id)
        .order_by(Assessment.created_at)
    )
    return list(result.scalars().all())


async def _get_assessment_and_offering(
    session: AsyncSession, assessment_id: uuid.UUID
) -> tuple[Assessment, CourseOffering]:
    assessment = await session.get(Assessment, assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    offering = await _get_offering_or_404(session, assessment.course_offering_id)
    return assessment, offering


@router.post("/assessments/{assessment_id}/grades", response_model=list[GradeResponse])
async def enter_grades(
    assessment_id: uuid.UUID,
    payload: GradeEntryRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Grade]:
    assessment, offering = await _get_assessment_and_offering(session, assessment_id)
    ensure_can_manage_offering(offering, claims)

    grades: list[Grade] = []
    for entry in payload.grades:
        if entry.score < 0 or entry.score > assessment.max_score:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"score must be between 0 and {assessment.max_score}",
            )
        existing = await session.execute(
            select(Grade).where(Grade.assessment_id == assessment_id, Grade.student_id == entry.student_id)
        )
        grade = existing.scalar_one_or_none()
        if grade is None:
            grade = Grade(
                institution_id=offering.institution_id,
                assessment_id=assessment_id,
                student_id=entry.student_id,
                score=Decimal(str(entry.score)),
            )
            session.add(grade)
        else:
            grade.score = Decimal(str(entry.score))
        grades.append(grade)

    await session.commit()
    return grades


@router.post("/assessments/{assessment_id}/publish", response_model=list[GradeResponse])
async def publish_grades(
    assessment_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Grade]:
    _, offering = await _get_assessment_and_offering(session, assessment_id)
    ensure_can_manage_offering(offering, claims)

    result = await session.execute(select(Grade).where(Grade.assessment_id == assessment_id))
    grades = list(result.scalars().all())
    for grade in grades:
        grade.published = True
    await session.commit()
    return grades


@router.get("/assessments/{assessment_id}/grades", response_model=list[GradeResponse])
async def list_grades(
    assessment_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[Grade]:
    query = select(Grade).where(Grade.assessment_id == assessment_id)
    if claims.get("role") == "student":
        query = query.where(Grade.student_id == uuid.UUID(claims["sub"]), Grade.published.is_(True))
    result = await session.execute(query)
    return list(result.scalars().all())


@router.post(
    "/grades/{grade_id}/appeals", response_model=GradeAppealResponse, status_code=status.HTTP_201_CREATED
)
async def create_appeal(
    grade_id: uuid.UUID,
    payload: GradeAppealCreateRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> GradeAppeal:
    if claims.get("role") != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only students submit appeals")
    student_id = uuid.UUID(claims["sub"])

    grade = await session.get(Grade, grade_id)
    if grade is None or grade.student_id != student_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found")
    if not grade.published:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Grade is not published yet")

    existing = await session.execute(
        select(GradeAppeal).where(
            GradeAppeal.grade_id == grade_id,
            GradeAppeal.status.in_([AppealStatus.SUBMITTED, AppealStatus.UNDER_REVIEW]),
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An open appeal already exists")

    appeal = GradeAppeal(
        institution_id=grade.institution_id, grade_id=grade_id, student_id=student_id, reason=payload.reason
    )
    session.add(appeal)
    await session.commit()
    return appeal


@router.get("/grades/{grade_id}/appeals", response_model=list[GradeAppealResponse])
async def list_appeals(
    grade_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[GradeAppeal]:
    grade = await session.get(Grade, grade_id)
    if grade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found")
    if claims.get("role") == "student" and grade.student_id != uuid.UUID(claims["sub"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found")

    result = await session.execute(select(GradeAppeal).where(GradeAppeal.grade_id == grade_id))
    return list(result.scalars().all())


_VALID_TRANSITIONS = {
    AppealStatus.SUBMITTED: {AppealStatus.UNDER_REVIEW, AppealStatus.ACCEPTED, AppealStatus.REJECTED},
    AppealStatus.UNDER_REVIEW: {AppealStatus.ACCEPTED, AppealStatus.REJECTED},
}


@router.post("/appeals/{appeal_id}/decision", response_model=GradeAppealResponse)
async def decide_appeal(
    appeal_id: uuid.UUID,
    payload: GradeAppealDecisionRequest,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> GradeAppeal:
    if claims.get("role") not in _STAFF_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")

    appeal = await session.get(GradeAppeal, appeal_id)
    if appeal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found")
    grade = await session.get(Grade, appeal.grade_id)
    if grade is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grade not found")
    assessment = await session.get(Assessment, grade.assessment_id)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assessment not found")
    offering = await _get_offering_or_404(session, assessment.course_offering_id)
    ensure_can_manage_offering(offering, claims)

    try:
        new_status = AppealStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status") from exc

    allowed = _VALID_TRANSITIONS.get(appeal.status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move appeal from {appeal.status.value} to {new_status.value}",
        )

    if new_status == AppealStatus.ACCEPTED:
        if payload.corrected_score is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="corrected_score is required to accept an appeal"
            )
        if payload.corrected_score < 0 or payload.corrected_score > assessment.max_score:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"corrected_score must be between 0 and {assessment.max_score}",
            )
        old_score = grade.score
        new_score = Decimal(str(payload.corrected_score))
        if new_score != old_score:
            session.add(
                GradeAuditLog(
                    institution_id=grade.institution_id,
                    grade_id=grade.id,
                    changed_by=uuid.UUID(claims["sub"]),
                    old_score=old_score,
                    new_score=new_score,
                    reason=f"Grade appeal {appeal.id} accepted",
                )
            )
            grade.score = new_score

    appeal.status = new_status
    appeal.reviewer_notes = payload.reviewer_notes
    appeal.decided_by = uuid.UUID(claims["sub"])
    appeal.decided_at = datetime.now(UTC)
    await session.commit()
    return appeal
