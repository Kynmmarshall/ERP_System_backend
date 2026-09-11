import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import ensure_can_manage_offering
from app.deps import get_current_claims, get_tenant_session
from app.models.courses import CourseOffering
from app.schemas import AtRiskStatus

router = APIRouter()

ATTENDANCE_THRESHOLD = 0.75
PASS_THRESHOLD = 50.0


def _resolve_student_id(claims: dict, student_id: uuid.UUID | None) -> uuid.UUID:
    role = claims.get("role")
    if role == "student":
        if student_id is not None and student_id != uuid.UUID(claims["sub"]):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Students may only view their own data")
        return uuid.UUID(claims["sub"])
    if student_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="student_id is required")
    return student_id


async def _attendance_rate(
    session: AsyncSession, *, course_offering_id: uuid.UUID, student_id: uuid.UUID
) -> float | None:
    result = await session.execute(
        text(
            """
            SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE ar.present) AS present
            FROM attendance_sessions s
            LEFT JOIN attendance_records ar
                ON ar.attendance_session_id = s.id AND ar.student_id = :student_id
            WHERE s.course_offering_id = :offering_id
            """
        ),
        {"offering_id": str(course_offering_id), "student_id": str(student_id)},
    )
    row = result.one()
    total, present = row.total, row.present
    if not total:
        return None
    return present / total


async def _assessment_average(
    session: AsyncSession, *, course_offering_id: uuid.UUID, student_id: uuid.UUID
) -> float | None:
    result = await session.execute(
        text(
            """
            SELECT (g.score / a.max_score * 100) AS pct
            FROM grades g
            JOIN assessments a ON a.id = g.assessment_id
            WHERE a.course_offering_id = :offering_id AND g.student_id = :student_id AND g.published = true
            ORDER BY a.created_at DESC
            LIMIT 2
            """
        ),
        {"offering_id": str(course_offering_id), "student_id": str(student_id)},
    )
    scores = [float(row.pct) for row in result.all()]
    if len(scores) < 2:
        return None
    return sum(scores) / len(scores)


async def _at_risk_status(
    session: AsyncSession, *, course_offering_id: uuid.UUID, student_id: uuid.UUID
) -> AtRiskStatus:
    attendance_rate = await _attendance_rate(
        session, course_offering_id=course_offering_id, student_id=student_id
    )
    assessment_average = await _assessment_average(
        session, course_offering_id=course_offering_id, student_id=student_id
    )
    at_risk = (attendance_rate is not None and attendance_rate < ATTENDANCE_THRESHOLD) or (
        assessment_average is not None and assessment_average < PASS_THRESHOLD
    )
    return AtRiskStatus(
        student_id=student_id,
        course_offering_id=course_offering_id,
        attendance_rate=attendance_rate,
        assessment_average=assessment_average,
        at_risk=at_risk,
    )


@router.get("/course-offerings/{course_offering_id}/at-risk", response_model=list[AtRiskStatus])
async def list_at_risk_students(
    course_offering_id: uuid.UUID,
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[AtRiskStatus]:
    offering = await session.get(CourseOffering, course_offering_id)
    if offering is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course offering not found")
    ensure_can_manage_offering(offering, claims)

    result = await session.execute(
        text("SELECT student_id FROM course_registrations WHERE course_offering_id = :offering_id"),
        {"offering_id": str(course_offering_id)},
    )
    student_ids = [row.student_id for row in result.all()]

    return [
        await _at_risk_status(session, course_offering_id=course_offering_id, student_id=student_id)
        for student_id in student_ids
    ]


@router.get("/me/at-risk", response_model=list[AtRiskStatus])
async def my_at_risk_status(
    claims: dict = Depends(get_current_claims), session: AsyncSession = Depends(get_tenant_session)
) -> list[AtRiskStatus]:
    if claims.get("role") != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Students only")
    student_id = uuid.UUID(claims["sub"])

    result = await session.execute(
        text("SELECT course_offering_id FROM course_registrations WHERE student_id = :student_id"),
        {"student_id": str(student_id)},
    )
    offering_ids = [row.course_offering_id for row in result.all()]

    return [
        await _at_risk_status(session, course_offering_id=offering_id, student_id=student_id)
        for offering_id in offering_ids
    ]


def _pdf_response(title: str, headers: list[str], rows: list[list[str]]) -> Response:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 12)]

    table_data = [headers, *rows] if rows else [headers, ["No data available"] + [""] * (len(headers) - 1)]
    table = Table(table_data, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    return Response(content=buffer.getvalue(), media_type="application/pdf")


@router.get("/reports/transcript")
async def transcript_report(
    student_id: uuid.UUID | None = Query(default=None),
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    resolved_student_id = _resolve_student_id(claims, student_id)

    result = await session.execute(
        text(
            """
            SELECT c.code, c.name, t.name AS term_name,
                   AVG(g.score / a.max_score * 100) AS average_pct
            FROM course_registrations cr
            JOIN course_offerings co ON co.id = cr.course_offering_id
            JOIN courses c ON c.id = co.course_id
            JOIN terms t ON t.id = co.term_id
            LEFT JOIN assessments a ON a.course_offering_id = co.id
            LEFT JOIN grades g ON g.assessment_id = a.id AND g.student_id = cr.student_id AND g.published = true
            WHERE cr.student_id = :student_id
            GROUP BY c.code, c.name, t.name, co.id
            ORDER BY t.name, c.code
            """
        ),
        {"student_id": str(resolved_student_id)},
    )
    rows = [
        [row.code, row.name, row.term_name, f"{row.average_pct:.1f}%" if row.average_pct is not None else "N/A"]
        for row in result.all()
    ]
    return _pdf_response("Academic Transcript", ["Code", "Course", "Term", "Average"], rows)


@router.get("/reports/attendance-summary")
async def attendance_summary_report(
    student_id: uuid.UUID | None = Query(default=None),
    term_id: uuid.UUID | None = Query(default=None),
    claims: dict = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    resolved_student_id = _resolve_student_id(claims, student_id)

    query = """
        SELECT c.code, c.name,
               COUNT(s.id) AS total_sessions,
               COUNT(*) FILTER (WHERE ar.present) AS present_sessions
        FROM course_registrations cr
        JOIN course_offerings co ON co.id = cr.course_offering_id
        JOIN courses c ON c.id = co.course_id
        LEFT JOIN attendance_sessions s ON s.course_offering_id = co.id
        LEFT JOIN attendance_records ar ON ar.attendance_session_id = s.id AND ar.student_id = cr.student_id
        WHERE cr.student_id = :student_id
    """
    params: dict[str, str] = {"student_id": str(resolved_student_id)}
    if term_id is not None:
        query += " AND co.term_id = :term_id"
        params["term_id"] = str(term_id)
    query += " GROUP BY c.code, c.name, co.id ORDER BY c.code"

    result = await session.execute(text(query), params)
    rows = []
    for row in result.all():
        total = row.total_sessions or 0
        present = row.present_sessions or 0
        pct = f"{(present / total * 100):.1f}%" if total else "No sessions"
        rows.append([row.code, row.name, str(present), str(total), pct])

    return _pdf_response("Attendance Summary", ["Code", "Course", "Present", "Total", "Percentage"], rows)
