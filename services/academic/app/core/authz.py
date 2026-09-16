from fastapi import HTTPException, status

from app.models.courses import CourseOffering


def ensure_can_manage_offering(offering: CourseOffering, claims: dict) -> None:
    """Object-ownership check: teaching staff may only manage (attendance/
    assessments/grades/appeals/exam schedule) a CourseOffering they are the
    instructor of. Admin/super_admin bypass - see phase4-plan.md.
    """
    role = claims.get("role")
    if role in ("admin", "super_admin"):
        return
    if role in ("staff", "lecturer") and claims.get("sub") == str(offering.instructor_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Not the instructor for this course offering"
    )
